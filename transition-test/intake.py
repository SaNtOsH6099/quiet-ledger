#!/usr/bin/env python3
"""Transition-test intake: fetch ALL files from a Drive staging folder.

Separate from pipeline.drive.echoes_intake on purpose. The shared
intake is for full Echoes renders and REQUIRES segment_map.json,
captions.json and a narration wav — it raises SystemExit
"missing required file in staging folder: ..." when any is absent.
The infinite-zoom staging folder holds only the 6 media files the
transition renderer needs, so the shared intake can never pass for
this test (run 44893661572 failed at exactly that step).

This intake has no segment_map / captions / narration requirement:
it lists the folder, downloads EVERY non-folder file in it by name
into --out-dir, and verifies the 6 expected media files are present
with size > 0. It never deletes anything from Drive.

Auth is the same OAuth-as-user flow as the shared pipeline
(DRIVE_OAUTH_JSON env, google.oauth2.credentials), implemented here
so this file is self-contained under transition-test/ and imports
nothing from pipeline/.
"""
import argparse
import io
import os
import sys

EXPECTED = [
    "68-B1-clip-v1.mp4",
    "68-B4b-still-v1.jpg",
    "68-B5b-clip-v1.mp4",
    "69-B4a-house-v1.jpg",
    "69-B4b-creature-v1.jpg",
    "69-B4b-reveal-v2.mp4",
]


def drive_service():
    from google.oauth2 import credentials as oauth_credentials
    from googleapiclient.discovery import build

    blob = os.environ.get("DRIVE_OAUTH_JSON")
    if not blob:
        raise SystemExit("no Drive auth: DRIVE_OAUTH_JSON is not set")
    import json

    info = json.loads(blob)
    creds = oauth_credentials.Credentials(
        None,
        refresh_token=info["refresh_token"],
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        token_uri=info.get("token_uri", "https://oauth2.googleapis.com/token"),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds)


def list_folder(service, folder_id):
    out, token = [], None
    while True:
        res = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken,files(id,name,size,mimeType)",
                pageSize=100,
                pageToken=token,
            )
            .execute()
        )
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
    ap = argparse.ArgumentParser(description="transition-test intake")
    ap.add_argument("--drive-folder-id", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--expected", default=",".join(EXPECTED),
                    help="comma-separated expected filenames")
    args = ap.parse_args()

    service = drive_service()
    entries = list_folder(service, args.drive_folder_id)
    print(f"{len(entries)} items in staging folder {args.drive_folder_id}")
    for e in entries:
        print(f"  {e['name']}: {e.get('size', '?')} bytes ({e['mimeType']})")

    files = [e for e in entries
             if e["mimeType"] != "application/vnd.google-apps.folder"]
    if not files:
        raise SystemExit("no files found in staging folder")
    os.makedirs(args.out_dir, exist_ok=True)
    total = 0
    for e in files:
        dest = os.path.join(args.out_dir, e["name"])
        download_file(service, e["id"], dest)
        size = os.path.getsize(dest)
        total += size
        print(f"downloaded {e['name']}: {size} bytes")

    expected = [n.strip() for n in args.expected.split(",") if n.strip()]
    missing = [n for n in expected
               if not os.path.exists(os.path.join(args.out_dir, n))]
    if missing:
        raise SystemExit(f"missing expected media files: {missing}")
    empty = [n for n in expected
             if os.path.getsize(os.path.join(args.out_dir, n)) == 0]
    if empty:
        raise SystemExit(f"expected media files downloaded empty: {empty}")
    print(f"transition intake OK: {len(files)} files, {total} bytes, "
          f"all {len(expected)} expected media present and non-empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
