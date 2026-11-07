#!/usr/bin/env python3
"""One video, one environment: a self-contained Drive folder per video.

Every video gets its own folder, "NNN - slug", inside the Drive root
folder. That folder holds EVERYTHING for the video, so the video is
fully separate from every other video and can be deleted, moved, or
re-rendered from its folder alone:

    NNN - slug/
      script.json         — the script: beats, scene code, codegen
                            version, provider, format. The source of
                            truth for the video's content.
      meta.json           — status, topic, timestamps, provider,
                            codegen version, drive links, run history.
      narration.wav       — the narration (kept so re-assembly does
                            not need to re-narrate).
      words.json          — word timings for captions.
      captions.ass        — the caption file.
      silent.mp4          — the rendered scenes, no audio.
      NNN - slug.mp4      — the finished video.
      NNN - slug-thumb.png — the thumbnail.

queue.json in the Drive root is only a THIN INDEX now: one entry per
video with {id, topic, status, folder_id, drive_link}. It points at
the video's folder; it does not hold the script. The script lives in
the video's own folder, so a video's content can never leak into
another video's, and deleting a video's folder deletes the video
entirely. The control app reads queue.json for the list and opens a
video's folder for its details.

This module is the only place that touches a video's folder. The
queue module (drive_queue.py) only touches queue.json. Render reads
the script from the folder; the ingest step writes it there (from a
script Muse submitted to the repo); upload files the finished video
there.
"""
import io
import json
import re

from pipeline.drive import drive_queue as queue_mod


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > 60:
        # Cut at a word boundary so a long topic never ends mid-word.
        cut = slug[:60].rsplit("-", 1)[0]
        slug = cut or slug[:60]
    return slug or "untitled"


def env_folder_name(entry_id, topic):
    """The video's folder name: "NNN - slug"."""
    return f"{entry_id:03d} - {slugify(topic)}"


def drive_service(key_file=None, oauth_file=None):
    from googleapiclient.discovery import build  # noqa: PLC0415

    return build(
        "drive", "v3",
        credentials=queue_mod.get_drive_credentials(key_file, oauth_file),
    )


def _escape_query_value(value):
    """Escape a string for use inside a Drive query literal.

    Drive query strings are single-quoted; a literal single quote
    is escaped as \\'. Without this, a name like "Ruby's pink
    01.svg" produces an invalid query (HttpError 400 "Invalid
    Value") and kills the sync."""
    return value.replace("'", "\\'")


def find_folder(service, name, parent_id):
    """Find a folder by name inside parent_id. Returns its id or None."""
    parent = parent_id or "root"
    query = (
        f"name = '{_escape_query_value(name)}' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false and '{parent}' in parents"
    )
    res = (
        service.files()
        .list(q=query, fields="files(id)", pageSize=5)
        .execute()
    )
    files = res.get("files", [])
    return files[0]["id"] if files else None


def find_or_create_folder(service, name, parent_id):
    """Find a folder by name inside parent_id, or create it."""
    found = find_folder(service, name, parent_id)
    if found:
        return found
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        meta["parents"] = [parent_id]
    done = service.files().create(body=meta, fields="id").execute()
    print(f"created folder {name}: {done.get('id')}")
    return done["id"]


def find_file(service, name, folder_id):
    """Find a file by name inside folder_id. Returns its id or None."""
    query = (f"name = '{_escape_query_value(name)}' "
             "and trashed = false")
    if folder_id:
        query += f" and '{folder_id}' in parents"
    res = (
        service.files()
        .list(q=query, fields="files(id)", pageSize=5)
        .execute()
    )
    files = res.get("files", [])
    return files[0]["id"] if files else None


def upload_file(service, folder_id, local_path, name):
    """Upload a local file into the folder, updating it if it exists.
    Returns the Drive file record (id, webViewLink)."""
    from googleapiclient.http import MediaFileUpload  # noqa: PLC0415

    media = MediaFileUpload(local_path, resumable=True)
    existing = find_file(service, name, folder_id)
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


def upload_bytes(service, folder_id, name, data, mimetype):
    """Upload bytes as a file into the folder, updating if it exists."""
    from googleapiclient.http import MediaIoBaseUpload  # noqa: PLC0415

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype)
    existing = find_file(service, name, folder_id)
    if existing:
        done = (
            service.files()
            .update(fileId=existing, media_body=media,
                    fields="id, webViewLink")
            .execute()
        )
    else:
        meta = {"name": name, "mimeType": mimetype}
        if folder_id:
            meta["parents"] = [folder_id]
        done = (
            service.files()
            .create(body=meta, media_body=media, fields="id, webViewLink")
            .execute()
        )
    return done


def download_bytes(service, folder_id, name):
    """Download a file's bytes from the folder. Returns bytes or None."""
    from googleapiclient.http import MediaIoBaseDownload  # noqa: PLC0415

    file_id = find_file(service, name, folder_id)
    if not file_id:
        return None
    req = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def save_json(service, folder_id, name, obj):
    """Write a JSON object into the folder."""
    data = json.dumps(obj, indent=2).encode("utf-8")
    return upload_bytes(service, folder_id, name, data,
                        "application/json")


def load_json(service, folder_id, name):
    """Read a JSON object from the folder. Returns None if missing."""
    raw = download_bytes(service, folder_id, name)
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


def save_script(service, folder_id, script):
    """Write script.json into the video's folder."""
    return save_json(service, folder_id, "script.json", script)


def load_script(service, folder_id):
    """Read script.json from the video's folder. None if missing."""
    return load_json(service, folder_id, "script.json")


def save_meta(service, folder_id, meta):
    """Write meta.json into the video's folder."""
    return save_json(service, folder_id, "meta.json", meta)


def load_meta(service, folder_id):
    """Read meta.json from the video's folder. None if missing."""
    return load_json(service, folder_id, "meta.json")


def create_env(service, root_folder_id, entry_id, topic, script=None):
    """Create the video's environment folder and seed it with
    script.json and meta.json. Returns the folder id. Idempotent:
    reuses the folder if it already exists."""
    name = env_folder_name(entry_id, topic)
    folder_id = find_or_create_folder(service, name, root_folder_id)
    if script is not None:
        save_script(service, folder_id, script)
    meta = load_meta(service, folder_id) or {}
    meta.update({
        "id": entry_id,
        "topic": topic,
        "folder": name,
        "status": meta.get("status", "script-ready"),
    })
    save_meta(service, folder_id, meta)
    return folder_id


def migrate_entry(service, root_folder_id, entry):
    """Move an old-format queue entry (script embedded in queue.json,
    no folder_id) into its own environment folder. Writes script.json
    and meta.json there, and returns the folder id. The caller then
    slims the queue entry to the thin index (id, topic, status,
    folder_id, drive_link). New-format entries (already have a
    folder_id) are returned unchanged."""
    if entry.get("folder_id"):
        return entry["folder_id"]
    script = entry.get("script")
    folder_id = create_env(
        service, root_folder_id, entry["id"], entry["topic"],
        script=script)
    meta = load_meta(service, folder_id) or {}
    meta.update({
        "status": entry.get("status", "script-ready"),
        "drive_link": entry.get("drive_link"),
    })
    save_meta(service, folder_id, meta)
    return folder_id
