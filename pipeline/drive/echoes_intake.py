#!/usr/bin/env python3
"""Intake for an Echoes render: fetch the locked inputs from the per-video
staging folder in the quiet-ledger Drive hub.

The per-video folder (e.g. "79 The Antikythera Mechanism" inside the
quiet-ledger Drive folder) holds the messy assets, made locally by the
per-video side chat:
  clips/            locked AI clips, one mp4 per segment (24 fps)
  narration_mix.wav (or narration*.wav) — Gemini Kore, one take
  captions.json     captions measured from the locked narration
  segment_map.json  [{"file": "C1.mp4", "start": 0.0, "end": 9.4}, ...]
  narration-timestamps_*.md — the caption plan / timestamps file, kept
                    alongside the final for the Echoes Drop upload
  date_cards.json   OPTIONAL (Hormozi only): Director-plan date cards,
                    [{"text": "MARCH 1995", "start": 7.94}, ...] (end
                    defaults to start + 3.0s); the captions job injects
                    them into BOTH caption layers before the render.
                    Absent = the video has no cards.
  hook_text.json    OPTIONAL (Hormozi only): Director-plan hook text,
                    {"text": "NO ONE EVER CAME FORWARD", "start": 0.0,
                    "end": 8.7} — the approved on-screen text on the
                    opening shot, in the lower-third safe zone for the
                    full shot; the captions job injects it into BOTH
                    caption layers before the render. Absent = the video
                    has no hook text.
  drone_bed.wav     OPTIONAL: a per-video drone bed (24kHz mono, -43 LUFS,
                    matched to the video's topic — the Gate 4 drone-bed
                    experiment). The assemble job mixes it under the
                    narration when the dispatch `bed` input names it;
                    absent = the video is voice-only.

Auth is OAuth as the user (DRIVE_OAUTH_JSON). A service account cannot
create files in a personal Drive folder, and is not used here.

This only DOWNLOADS. It never deletes anything from Drive. Cleaning the
staging folder after the final is transferred to Echoes Drop is a Hub
step (see docs/ECHOES.md), not an Actions step.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def list_folder(service, folder_id):
    out, token = [], None
    while True:
        res = (service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken,files(id,name,size,mimeType)",
            pageSize=100, pageToken=token).execute())
        out.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            return out


def download_file(service, file_id, dest):
    from googleapiclient.http import MediaIoBaseDownload
    req = service.files().get_media(fileId=file_id)
    with io.FileIO(dest, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def main():
    parser = argparse.ArgumentParser(description="intake Echoes render inputs")
    parser.add_argument("--drive-folder-id", required=True,
                        help="per-video staging folder id in quiet-ledger")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    import video_env as env  # noqa: PLC0415

    service = env.drive_service()
    entries = list_folder(service, args.drive_folder_id)
    print(f"{len(entries)} items in staging folder {args.drive_folder_id}")
    by_name = {e["name"]: e for e in entries}
    clips_dir = os.path.join(args.out_dir, "clips")
    os.makedirs(clips_dir, exist_ok=True)

    # Clips: either a clips/ subfolder, or mp4s at the folder root.
    clips_folder = next(
        (e for e in entries
         if e["name"] == "clips"
         and e["mimeType"] == "application/vnd.google-apps.folder"),
        None)
    if clips_folder:
        clip_entries = list_folder(service, clips_folder["id"])
    else:
        clip_entries = [e for e in entries if e["name"].endswith(".mp4")]
    if not clip_entries:
        raise SystemExit("no locked clips found in staging folder")
    for e in clip_entries:
        dest = os.path.join(clips_dir, e["name"])
        download_file(service, e["id"], dest)
        print(f"clip {e['name']}: {os.path.getsize(dest)} bytes")

    required = ["segment_map.json", "captions.json"]
    for name in required:
        if name not in by_name:
            raise SystemExit(f"missing required file in staging folder: {name}")
        dest = os.path.join(args.out_dir, name)
        download_file(service, by_name[name]["id"], dest)
        print(f"{name}: {os.path.getsize(dest)} bytes")

    narration = [e for e in entries
                 if e["name"].endswith(".wav") and "narration" in e["name"].lower()]
    if not narration:
        raise SystemExit("no narration wav found in staging folder")
    dest = os.path.join(args.out_dir, "narration_mix.wav")
    download_file(service, narration[0]["id"], dest)
    print(f"narration {narration[0]['name']}: {os.path.getsize(dest)} bytes")

    timestamps = [e for e in entries
                  if e["name"].startswith("narration-timestamps")
                  and e["name"].endswith(".md")]
    for e in timestamps:
        dest = os.path.join(args.out_dir, e["name"])
        download_file(service, e["id"], dest)
        print(f"timestamps {e['name']}: {os.path.getsize(dest)} bytes")

    # Date cards: optional. When the staging folder holds a
    # date_cards.json (Director-plan date cards, a locked Gate 3
    # element), the captions job injects them into BOTH caption layers
    # before the render; without it a GitHub render silently drops
    # them (69 Gate 4). Videos without cards stage no such file and
    # render exactly as before.
    if "date_cards.json" in by_name:
        dest = os.path.join(args.out_dir, "date_cards.json")
        download_file(service, by_name["date_cards.json"]["id"], dest)
        print(f"date_cards.json: {os.path.getsize(dest)} bytes")

    # Hook text: optional. When the staging folder holds a
    # hook_text.json (Director-plan hook text, a locked Gate 0
    # element), the captions job injects it into BOTH caption layers
    # before the render; without it a GitHub render silently drops
    # it (63 Gate 4). Videos without a hook text stage no such file
    # and render exactly as before.
    if "hook_text.json" in by_name:
        dest = os.path.join(args.out_dir, "hook_text.json")
        download_file(service, by_name["hook_text.json"]["id"], dest)
        print(f"hook_text.json: {os.path.getsize(dest)} bytes")

    # Drone bed: optional. When the staging folder holds a
    # drone_bed.wav (a per-video drone bed, -43 LUFS, matched to the
    # video's topic — the Gate 4 drone-bed experiment), the intake
    # fetches it so the assemble job can mix it under the narration;
    # without it the render is voice-only. Absent = the video has no
    # bed. The bed is staged under the fixed name drone_bed.wav (like
    # narration_mix.wav); the dispatch `bed` input names it for the
    # assemble step, and the assemble script fails loudly if the named
    # file was not fetched.
    if "drone_bed.wav" in by_name:
        dest = os.path.join(args.out_dir, "drone_bed.wav")
        download_file(service, by_name["drone_bed.wav"]["id"], dest)
        print(f"drone_bed.wav: {os.path.getsize(dest)} bytes")

    seg_map = json.load(open(os.path.join(args.out_dir, "segment_map.json")))
    missing = [s["file"] for s in seg_map
               if not os.path.exists(os.path.join(clips_dir, s["file"]))]
    if missing:
        raise SystemExit(f"segment map names clips that were not fetched: {missing}")
    print(f"intake OK: {len(clip_entries)} clips, {len(seg_map)} segments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
