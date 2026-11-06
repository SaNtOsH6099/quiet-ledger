#!/usr/bin/env python3
"""Self-repair: ask the pipeline's own brain to fix broken code.

When a render run fails, the repair job feeds the error text and the
repo's code files to the brain (the same Groq -> Gemini -> NVIDIA
rotation draft.py uses). The brain diagnoses which file is wrong and
returns the corrected full file content. This script validates the fix
(python compiles, yaml parses) and writes it back.

Usage: repair.py --error "the error text" [--repo .] [--dry-run]
       repair.py --error-file error.txt [--repo .]
Stdlib only. Keys come from the environment, never from files:
  GROQ_API_KEYS, GEMINI_API_KEYS, NVIDIA_API_KEYS
"""
import argparse
import ast
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from draft import generate  # noqa: E402 - reuse the brain rotation

# Files the brain is allowed to fix. Keep this narrow on purpose: the
# repair loop must not rewrite secrets, the queue, or the workflow's
# own repair logic.
REPAIRABLE_DIRS = ("scripts", "templates")
REPAIRABLE_EXTS = (".py", ".html", ".json")
# The workflow file itself is repairable too (ffmpeg installs live there).
REPAIRABLE_FILES = (".github/workflows/pipeline.yml",)


def collect_files(repo):
    """Return {rel_path: content} for every repairable file."""
    out = {}
    for rel in REPAIRABLE_FILES:
        p = os.path.join(repo, rel)
        if os.path.isfile(p):
            out[rel] = open(p, encoding="utf-8").read()
    for d in REPAIRABLE_DIRS:
        base = os.path.join(repo, d)
        for root, _dirs, files in os.walk(base):
            for f in sorted(files):
                if f.endswith(REPAIRABLE_EXTS):
                    p = os.path.join(root, f)
                    rel = os.path.relpath(p, repo)
                    out[rel] = open(p, encoding="utf-8").read()
    return out


REPAIR_SYSTEM = """You fix broken code in a small video pipeline. You are given
an error message and the contents of the pipeline's code files. Diagnose
which ONE file is wrong and return the corrected FULL content of that file.

Rules:
- Fix ONLY the root cause of the error. Make the smallest change that
  fixes it. Do not refactor, do not rename things, do not change
  behaviour unrelated to the error.
- Return ONLY a JSON object with this exact shape:
  {"file": "relative/path/to/file", "content": "full corrected file content", "summary": "one sentence saying what was wrong and what changed"}
- The "file" must be one of the files you were given. Never invent a
  new file path.
- The "content" must be the COMPLETE file, not a diff and not a snippet.
- No markdown. No text outside the JSON object.
"""


def repair_prompt(error, files):
    listing = "\n".join(f"--- {path} ---" for path in files)
    bodies = []
    for path, content in files.items():
        # Cap each file so the prompt stays within the model's budget.
        # The pipeline's files are small; 12k chars each is plenty.
        bodies.append(f"--- {path} ---\n{content[:12000]}")
    return (
        f"Error:\n{error}\n\n"
        f"Files:\n{listing}\n\n"
        + "\n\n".join(bodies)
        + "\n\nReturn the JSON object with the fixed file."
    )


def validate_repair(obj, files):
    """Check the brain's repair reply. Returns a list of problems."""
    problems = []
    if not isinstance(obj, dict):
        return ["top level is not a JSON object"]
    f = obj.get("file")
    content = obj.get("content")
    if not isinstance(f, str) or f not in files:
        problems.append(f"'file' must be one of the given files, got {f!r}")
        return problems
    if not isinstance(content, str) or not content.strip():
        problems.append("'content' is missing or empty")
        return problems
    if content.strip() == files[f].strip():
        problems.append("the fix is identical to the current file (no change)")
    if f.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            problems.append(f"fixed {f} does not parse as Python: {e}")
    elif f.endswith((".yml", ".yaml")):
        try:
            import yaml  # noqa: PLC0415 - only needed for yaml files

            yaml.safe_load(content)
        except ImportError:
            pass  # yaml not installed locally; the workflow validates it
        except Exception as e:  # noqa: BLE001
            problems.append(f"fixed {f} does not parse as YAML: {e}")
    return problems


def repair(error, repo):
    """Ask the brain for a fix. Returns (path, content, summary)."""
    files = collect_files(repo)
    if not files:
        raise RuntimeError("no repairable files found")
    obj, provider = generate(
        REPAIR_SYSTEM,
        repair_prompt(error, files),
        lambda o: validate_repair(o, files),
        "repair",
    )
    return obj["file"], obj["content"], obj.get("summary", ""), provider


# Markers that the failure is in the brain-written scene code (stored in
# the queue entry), not in a repo file. A HyperFrames check failure
# means the code for one beat is bad; patching a repo file cannot fix
# it. The repair job regenerates the scene code instead.
SCENE_CODE_MARKERS = (
    "hyperframes check",
    "Check failed",
    "missing_gsap_plugin",
    "motionPath",
    "text_box_overflow",
    "content_overlap",
    "caption_exit_missing_hard_kill",
    "Layout",
    "missing_hard_kill",
)


def is_scene_code_error(error):
    """True when the error is a bad brain-written scene, not a repo bug."""
    low = error.lower()
    return any(m.lower() in low for m in SCENE_CODE_MARKERS)


def main():
    parser = argparse.ArgumentParser(description="self-repair via the brain")
    parser.add_argument("--error", default=None, help="error text")
    parser.add_argument("--error-file", default=None,
                        help="file holding the error text")
    parser.add_argument("--repo", default=".",
                        help="repo root (default: current dir)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the fix, do not write it")
    args = parser.parse_args()
    if args.error_file:
        error = open(args.error_file, encoding="utf-8").read()
    elif args.error:
        error = args.error
    else:
        print("need --error or --error-file", file=sys.stderr)
        return 2
    if not error.strip():
        print("error text is empty", file=sys.stderr)
        return 2
    if is_scene_code_error(error):
        # The scene code (in the queue entry) is bad; no repo file can
        # fix it. Exit 3 so the workflow regenerates the code instead.
        print("the failure is in the brain-written scene code, not a "
              "repo file; regenerate the code", file=sys.stderr)
        return 3
    path, content, summary, provider = repair(error.strip(), args.repo)
    print(f"brain ({provider}) will fix {path}: {summary}", flush=True)
    if args.dry_run:
        print(content)
        return 0
    full = os.path.join(args.repo, path)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"wrote {full}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
