#!/usr/bin/env python3
"""Send the finished file and its thumbnail to Google Drive.

The service account key comes from DRIVE_SERVICE_ACCOUNT_JSON (JSON text
in the environment) or --key-file. The destination is DRIVE_FOLDER_ID
(or --folder-id); empty means the Drive root. Files are named
"NN - slug.mp4" from the queue id and topic, so Drive stays in order.
After a successful upload the queue entry is marked in-drive with the
Drive web link (via queue.py's update command logic, imported here).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "untitled"


def drive_service(key_file=None, oauth_file=None):
    from googleapiclient.discovery import build  # noqa: PLC0415

    import queue as queue_mod  # noqa: PLC0415

    return build(
        "drive", "v3",
        credentials=queue_mod.get_drive_credentials(key_file, oauth_file),
    )


def find_existing(service, name, folder_id):
    query = f"name = '{name}' and trashed = false"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    res = (
        service.files()
        .list(q=query, fields="files(id)", pageSize=5)
        .execute()
    )
    files = res.get("files", [])
    return files[0]["id"] if files else None


def upload(service, path, name, folder_id):
    from googleapiclient.http import MediaFileUpload  # noqa: PLC0415

    media = MediaFileUpload(path, resumable=True)
    existing = find_existing(service, name, folder_id)
    if existing:
        done = (
            service.files()
            .update(fileId=existing, media_body=media,
                    fields="id, webViewLink")
            .execute()
        )
        print(f"updated {name}: {done.get('webViewLink')}")
    else:
        meta = {"name": name}
        if folder_id:
            meta["parents"] = [folder_id]
        done = (
            service.files()
            .create(body=meta, media_body=media, fields="id, webViewLink")
            .execute()
        )
        print(f"uploaded {name}: {done.get('webViewLink')}")
    return done


def main():
    parser = argparse.ArgumentParser(description="upload the finished file")
    parser.add_argument("--file", required=True, help="finished mp4")
    parser.add_argument("--thumbnail", default=None)
    parser.add_argument("--queue-id", type=int, required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--key-file", default=None)
    parser.add_argument("--oauth-file", default=None)
    parser.add_argument("--folder-id",
                        default=os.environ.get("DRIVE_FOLDER_ID"))
    args = parser.parse_args()

    service = drive_service(args.key_file, args.oauth_file)
    base = f"{args.queue_id:03d} - {slugify(args.topic)}"
    main_file = upload(service, args.file, base + ".mp4", args.folder_id)
    if args.thumbnail:
        upload(service, args.thumbnail, base + "-thumb.png", args.folder_id)

    import queue as queue_mod  # noqa: PLC0415

    q, file_id = queue_mod.load_queue(service, args.folder_id)
    found = False
    for entry in q.get("entries", []):
        if entry.get("id") == args.queue_id:
            entry["status"] = "in-drive"
            entry["drive_link"] = main_file.get("webViewLink")
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
