#!/usr/bin/env python3
"""Ingest a submitted script into its video environment.

Muse writes the script (script + beats + scene code), validates it,
renders a demo locally, and pushes it to the repo under
submissions/<slug>/script.json. This module takes that file and files
it in Drive: it validates the scene code first (so a bad script never
reaches Drive), then creates or reuses the video's own environment
folder, saves script.json there, and marks the queue entry approved
so the render chain picks it up.

Usage: ingest.py [--submissions-dir submissions] [--queue-id N]

- With --queue-id N, the submission is filed into queue entry N (an
  explicit re-render of that entry, whatever its current status).
- Without it, the submission is matched to an existing entry by topic
  (exact match); if none exists, a new entry is created.
- A submission whose entry is already in-drive (finished) or
  rendering is skipped unless --queue-id was given explicitly: a
  re-submit must not silently re-queue a finished video.
- With no submissions in the directory, it exits quietly (0): the
  schedule runs ingest on every run, and most mornings there is
  nothing new to ingest.

Runs in the ingest job, before voice. Needs the Drive secrets
(DRIVE_OAUTH_JSON / DRIVE_SERVICE_ACCOUNT_JSON / DRIVE_FOLDER_ID)
and node (the validator checks JS syntax with node --check).
"""
import argparse
import glob
import json
import os
import sys

from pipeline.drive import drive_queue as queue_mod
from pipeline.drive import video_env as env
from pipeline.validate.scene import split_sentences, stored_code_is_fresh


def validate_script_obj(obj):
    """Check a submitted script.json: script text, beat coverage, and
    scene code. Returns a list of problems (empty means valid)."""
    problems = []
    if not isinstance(obj, dict):
        return ["top level is not a JSON object"]
    script = obj.get("script")
    if not isinstance(script, str) or not script.strip():
        problems.append("missing or empty 'script'")
        return problems
    if "\u2014" in script or "\u2013" in script:
        problems.append("script contains a dash character (use plain words)")
    words = script.split()
    if not 55 <= len(words) <= 110:
        problems.append(f"script is {len(words)} words, want 55 to 110")
    beats = obj.get("beats")
    if not isinstance(beats, list) or not 3 <= len(beats) <= 7:
        problems.append("beats must be a list of 3 to 7 items")
        return problems
    sentences = split_sentences(script)
    seen = []
    for i, beat in enumerate(beats):
        if not isinstance(beat, dict):
            problems.append(f"beat {i} is not an object")
            continue
        idx = beat.get("sentences")
        if not isinstance(idx, list) or not idx or not all(
            isinstance(n, int) and 0 <= n < len(sentences) for n in idx
        ):
            problems.append(f"beat {i} has bad sentence indices {idx!r}")
            continue
        seen.extend(idx)
        idea = beat.get("idea")
        if not isinstance(idea, str) or len(idea.strip()) < 10:
            problems.append(f"beat {i} is missing a visual idea")
    if seen != sorted(seen) or sorted(seen) != list(range(len(sentences))):
        problems.append(
            f"beats must cover sentences 0..{len(sentences) - 1} "
            f"exactly once, got {seen}"
        )
    # scene code: version + per-beat validation (structure, big text,
    # CSS widths, JS syntax, hard kill).
    fmt = obj.get("format", "shorts")
    problems.extend(stored_code_is_fresh(obj, fmt))
    return problems


def find_or_create_entry(queue, topic):
    """Find the entry with this topic, or create a new one. Returns
    (entry, created)."""
    for entry in queue.get("entries", []):
        if entry.get("topic") == topic:
            return entry, False
    used = {e.get("id") for e in queue.get("entries", [])}
    new_id = 1
    while new_id in used:
        new_id += 1
    entry = {
        "id": new_id,
        "topic": topic,
        "status": "idea",
        "folder_id": None,
        "drive_link": None,
    }
    queue.setdefault("entries", []).append(entry)
    return entry, True


def ingest_one(service, root, queue, queue_file_id, script_obj,
               slug, queue_id=None):
    """File one submitted script into Drive. Returns the entry id,
    or None if the submission was skipped."""
    topic = script_obj.get("topic") or slug.replace("-", " ")
    # target entry: explicit id, else match by topic, else create
    entry = None
    if queue_id is not None:
        entry = next((e for e in queue.get("entries", [])
                      if e.get("id") == queue_id), None)
        if entry is None:
            raise RuntimeError(
                f"no queue entry with id {queue_id!r}")
    else:
        entry, created = find_or_create_entry(queue, topic)
        if created:
            print(f"created queue entry {entry['id']} for {topic!r}")
    # never silently re-queue a finished video or clobber a render in
    # flight; an explicit --queue-id is the only override
    if queue_id is None and entry.get("status") in ("in-drive", "rendering"):
        print(f"skipping {topic!r}: entry {entry['id']} is already "
              f"{entry['status']}; pass --queue-id {entry['id']} to "
              "re-render it explicitly")
        return None
    folder_id = env.create_env(service, root, entry["id"], topic,
                               script=script_obj)
    entry["status"] = "approved"
    entry["folder_id"] = folder_id
    entry.pop("script", None)
    entry.pop("scenes", None)
    queue_mod.save_queue(service, root, queue, queue_file_id)
    meta = env.load_meta(service, folder_id) or {}
    meta.update({"status": "approved", "topic": topic})
    env.save_meta(service, folder_id, meta)
    print(f"ingested {topic!r} into entry {entry['id']} "
          f"(folder {folder_id}), marked approved")
    return entry["id"]


def main():
    parser = argparse.ArgumentParser(
        description="ingest submitted scripts into Drive")
    parser.add_argument("--submissions-dir", default="submissions")
    parser.add_argument("--queue-id", type=int, default=None,
                        help="file the submission into this queue entry "
                             "(explicit re-render)")
    args = parser.parse_args()
    paths = sorted(glob.glob(
        os.path.join(args.submissions_dir, "*", "script.json")))
    if not paths:
        print("no submissions to ingest")
        return 0
    service = env.drive_service()
    root = os.environ.get("DRIVE_FOLDER_ID")
    queue, queue_file_id = queue_mod.load_queue(service, root)
    ingested = []
    for path in paths:
        slug = os.path.basename(os.path.dirname(path))
        try:
            script_obj = json.load(open(path))
        except (OSError, ValueError) as e:
            print(f"{path}: cannot read script.json: {e}", file=sys.stderr)
            return 1
        problems = validate_script_obj(script_obj)
        if problems:
            print(f"{path}: script fails validation; not ingested:",
                  file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 1
        try:
            entry_id = ingest_one(service, root, queue, queue_file_id,
                                  script_obj, slug,
                                  queue_id=args.queue_id)
        except RuntimeError as e:
            print(f"{path}: {e}", file=sys.stderr)
            return 1
        if entry_id is not None:
            ingested.append(entry_id)
    print(f"ingested {len(ingested)} submission(s): {ingested}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
