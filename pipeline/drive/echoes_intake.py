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

    seg_map = json.load(open(os.path.join(args.out_dir, "segment_map.json")))
    missing = [s["file"] for s in seg_map
               if not os.path.exists(os.path.join(clips_dir, s["file"]))]
    if missing:
        raise SystemExit(f"segment map names clips that were not fetched: {missing}")
    print(f"intake OK: {len(clip_entries)} clips, {len(seg_map)} segments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
