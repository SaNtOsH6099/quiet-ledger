#!/usr/bin/env python3
"""The queue: one queue.json file in Google Drive, the single source of truth.

Entries: {"id", "topic", "status", "script", "scenes", "drive_link"}
Status flow: idea -> script-ready -> approved -> rendering -> in-drive -> posted
The control app edits this file later; the jobs read it through the same
service account. If Drive is not configured, every command fails with a
clear message and the caller falls back to a manual topic.

Auth: DRIVE_SERVICE_ACCOUNT_JSON env var holds the service account JSON
text, or --key-file points at the JSON file. DRIVE_FOLDER_ID env var (or
--folder-id) is the Drive folder that holds queue.json; empty means the
Drive root.
"""
import argparse
import io
import json
import os
import sys

QUEUE_NAME = "queue.json"


def _drive_service(key_file=None):
    from google.oauth2 import service_account  # noqa: PLC0415
    from googleapiclient.discovery import build  # noqa: PLC0415

    scopes = ["https://www.googleapis.com/auth/drive"]
    if key_file:
        creds = service_account.Credentials.from_service_account_file(
            key_file, scopes=scopes
        )
    else:
        blob = os.environ.get("DRIVE_SERVICE_ACCOUNT_JSON")
        if not blob:
            raise RuntimeError(
                "no service account: set DRIVE_SERVICE_ACCOUNT_JSON "
                "or pass --key-file"
            )
        info = json.loads(blob)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=scopes
        )
    return build("drive", "v3", credentials=creds)


def _find_queue(service, folder_id):
    query = f"name = '{QUEUE_NAME}' and trashed = false"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    res = (
        service.files()
        .list(q=query, fields="files(id, name)", pageSize=5)
        .execute()
    )
    files = res.get("files", [])
    return files[0]["id"] if files else None


def load_queue(service, folder_id):
    from googleapiclient.http import MediaIoBaseDownload  # noqa: PLC0415

    file_id = _find_queue(service, folder_id)
    if not file_id:
        return {"entries": []}, None
    req = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return json.loads(buf.getvalue().decode("utf-8")), file_id


def save_queue(service, folder_id, queue, file_id):
    from googleapiclient.http import MediaIoBaseUpload  # noqa: PLC0415

    data = json.dumps(queue, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/json")
    if file_id:
        service.files().update(
            fileId=file_id, media_body=media
        ).execute()
    else:
        meta = {"name": QUEUE_NAME, "mimeType": "application/json"}
        if folder_id:
            meta["parents"] = [folder_id]
        service.files().create(body=meta, media_body=media).execute()


def next_entry(queue, status):
    for entry in queue.get("entries", []):
        if entry.get("status") == status:
            return entry
    return None


def cmd_next(args):
    service = _drive_service(args.key_file)
    queue, _ = load_queue(service, args.folder_id)
    entry = next_entry(queue, args.status)
    if not entry:
        print(f"no queue entry with status {args.status!r}", file=sys.stderr)
        return 1
    print(json.dumps(entry))
    return 0


def cmd_get(args):
    service = _drive_service(args.key_file)
    queue, _ = load_queue(service, args.folder_id)
    for entry in queue.get("entries", []):
        if entry.get("id") == args.id:
            print(json.dumps(entry))
            return 0
    print(f"no queue entry with id {args.id!r}", file=sys.stderr)
    return 1


def cmd_add(args):
    service = _drive_service(args.key_file)
    queue, file_id = load_queue(service, args.folder_id)
    used = {e.get("id") for e in queue.get("entries", [])}
    new_id = 1
    while new_id in used:
        new_id += 1
    entry = {
        "id": new_id,
        "topic": args.topic,
        "status": "idea",
        "script": None,
        "scenes": None,
        "drive_link": None,
    }
    queue.setdefault("entries", []).append(entry)
    save_queue(service, args.folder_id, queue, file_id)
    print(json.dumps(entry))
    return 0


def cmd_update(args):
    service = _drive_service(args.key_file)
    queue, file_id = load_queue(service, args.folder_id)
    for entry in queue.get("entries", []):
        if entry.get("id") == args.id:
            if args.status:
                entry["status"] = args.status
            if args.script_file:
                entry["script"] = json.load(open(args.script_file))
            if args.scenes_file:
                entry["scenes"] = json.load(open(args.scenes_file))
            if args.link:
                entry["drive_link"] = args.link
            save_queue(service, args.folder_id, queue, file_id)
            print(json.dumps(entry))
            return 0
    print(f"no queue entry with id {args.id!r}", file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description="Drive queue for quiet-ledger")
    parser.add_argument("--key-file", default=None)
    parser.add_argument("--folder-id", default=os.environ.get("DRIVE_FOLDER_ID"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("next", help="print the next entry with a status")
    p.add_argument("--status", default="approved")
    p.set_defaults(fn=cmd_next)
    p = sub.add_parser("get", help="print one entry by id")
    p.add_argument("--id", type=int, required=True)
    p.set_defaults(fn=cmd_get)
    p = sub.add_parser("add", help="add a topic as a new idea")
    p.add_argument("--topic", required=True)
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("update", help="update one entry")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--status", default=None)
    p.add_argument("--script-file", default=None)
    p.add_argument("--scenes-file", default=None)
    p.add_argument("--link", default=None)
    p.set_defaults(fn=cmd_update)
    args = parser.parse_args()
    try:
        return args.fn(args)
    except RuntimeError as e:
        print(f"queue error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
