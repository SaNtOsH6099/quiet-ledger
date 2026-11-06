#!/usr/bin/env python3
"""File the finished video and everything it was built from into the
video's own environment folder in Google Drive.

The video's folder (see pipeline/drive/video_env.py) holds the whole
environment: script.json, meta.json, narration.wav, words.json,
captions.ass, silent.mp4, the finished "NNN - slug.mp4" and its
thumbnail. Re-runs reuse the same folder and update the same-named
files instead of creating duplicates, so the folder is always the
video's current state. queue.json stays in the Drive root as a thin
index; after a successful upload the queue entry is marked in-drive
with the Drive web link.

Drive access is OAuth as the user (DRIVE_OAUTH_JSON in the
environment, or --oauth-file); a service account cannot create files
in a personal Drive folder.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(
        description="file the finished video in its environment folder")
    parser.add_argument("--file", required=True, help="finished mp4")
    parser.add_argument("--thumbnail", default=None)
    parser.add_argument("--script", default=None,
                        help="script.json to file alongside the video")
    parser.add_argument("--narration", default=None,
                        help="narration.wav to file alongside the video")
    parser.add_argument("--words", default=None,
                        help="words.json to file alongside the video")
    parser.add_argument("--captions", default=None,
                        help="captions.ass to file alongside the video")
    parser.add_argument("--silent", default=None,
                        help="silent.mp4 to file alongside the video")
    parser.add_argument("--queue-id", type=int, required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--key-file", default=None)
    parser.add_argument("--oauth-file", default=None)
    parser.add_argument("--folder-id",
                        default=os.environ.get("DRIVE_FOLDER_ID"))
    args = parser.parse_args()

    import drive_queue as queue_mod  # noqa: PLC0415
    import video_env as env_mod  # noqa: PLC0415

    service = env_mod.drive_service(args.key_file, args.oauth_file)
    base = env_mod.env_folder_name(args.queue_id, args.topic)
    # The video's environment folder: created at draft time, reused
    # here. Everything for this video lives in it, nothing else.
    video_folder = env_mod.find_or_create_folder(
        service, base, args.folder_id)

    main_file = env_mod.upload_file(
        service, video_folder, args.file, base + ".mp4")
    if args.thumbnail:
        env_mod.upload_file(
            service, video_folder, args.thumbnail, base + "-thumb.png")
    # File the build inputs too, so the folder is the whole
    # environment and the video can be re-assembled from it alone.
    if args.script:
        env_mod.upload_file(service, video_folder, args.script,
                            "script.json")
    if args.narration:
        env_mod.upload_file(service, video_folder, args.narration,
                            "narration.wav")
    if args.words:
        env_mod.upload_file(service, video_folder, args.words,
                            "words.json")
    if args.captions:
        env_mod.upload_file(service, video_folder, args.captions,
                            "captions.ass")
    if args.silent:
        env_mod.upload_file(service, video_folder, args.silent,
                            "silent.mp4")

    # Update the video's meta.json with the finished state.
    meta = env_mod.load_meta(service, video_folder) or {}
    meta.update({
        "id": args.queue_id,
        "topic": args.topic,
        "status": "in-drive",
        "drive_link": main_file.get("webViewLink"),
    })
    env_mod.save_meta(service, video_folder, meta)

    # Mark the thin queue entry in-drive, pointing at the folder.
    q, file_id = queue_mod.load_queue(service, args.folder_id)
    found = False
    for entry in q.get("entries", []):
        if entry.get("id") == args.queue_id:
            entry["status"] = "in-drive"
            entry["folder_id"] = video_folder
            entry["drive_link"] = main_file.get("webViewLink")
            entry.pop("script", None)
            entry.pop("scenes", None)
            found = True
            break
    queue_mod.save_queue(service, args.folder_id, q, file_id)
    if found:
        print(f"queue entry {args.queue_id} marked in-drive")
    else:
        print(f"warning: no queue entry {args.queue_id} to mark in-drive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
