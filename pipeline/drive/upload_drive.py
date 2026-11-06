#!/usr/bin/env python3
"""Send the finished file and its thumbnail to Google Drive.

Drive access is OAuth as the user (DRIVE_OAUTH_JSON in the
environment, or --oauth-file); a service account cannot create files
in a personal Drive folder. The destination is DRIVE_FOLDER_ID
(or --folder-id); empty means the Drive root. Each video gets its own
folder "NN - slug" inside the destination, holding "NN - slug.mp4"
and "NN - slug-thumb.png", so the root never floods with files and
each video's files stay together. queue.json stays in the root.
Re-runs reuse the same folder and update the same-named files instead
of creating duplicates. After a successful upload the queue entry is
marked in-drive with the Drive web link (via drive_queue.py's update command
logic, imported here).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > 60:
        # Cut at a word boundary so a long topic never ends mid-word.
        cut = slug[:60].rsplit("-", 1)[0]
        slug = cut or slug[:60]
    return slug or "untitled"


def find_or_create_folder(service, name, parent_id):
    """Find a folder by name inside parent_id, or create it."""
    parent = parent_id or "root"
    query = (
        f"name = '{name}' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false and '{parent}' in parents"
    )
    res = (
        service.files()
        .list(q=query, fields="files(id)", pageSize=5)
        .execute()
    )
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        meta["parents"] = [parent_id]
    done = service.files().create(body=meta, fields="id").execute()
    print(f"created folder {name}: {done.get('id')}")
    return done["id"]


def drive_service(key_file=None, oauth_file=None):
    from googleapiclient.discovery import build  # noqa: PLC0415

    import drive_queue as queue_mod  # noqa: PLC0415

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
    # Each video gets its own folder inside the Drive folder, so the
    # root never floods with files. The video and its thumbnail live
    # in "NN - slug/" and are named "NN - slug.mp4" and
    # "NN - slug-thumb.png". queue.json stays in the root.
    video_folder = find_or_create_folder(service, base, args.folder_id)
    main_file = upload(service, args.file, base + ".mp4", video_folder)
    if args.thumbnail:
        upload(service, args.thumbnail, base + "-thumb.png", video_folder)

    import drive_queue as queue_mod  # noqa: PLC0415

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
