#!/usr/bin/env python3
"""Fetch a pack asset's SVG text from Google Drive.

The pack's asset files live on Drive, under the quiet-ledger folder,
in an `assets/` subfolder mirroring the category structure. The
catalog's "file" field is the path relative to that `assets/` folder
(e.g. "landmarks/eiffel-tower.svg" is
<DRIVE_FOLDER_ID>/assets/landmarks/eiffel-tower.svg). The catalog
itself lives in the repo, so the resolver reads the catalog locally
and fetches only the assets a beat actually uses, at render time,
from Drive.

The Drive service comes from pipeline.drive.video_env (OAuth as the
user, DRIVE_OAUTH_JSON, the same credentials the ingest and upload
jobs use). The import is lazy, inside fetch_asset_text, so this module
-- and resolve.py, which imports it -- still imports on a machine
without the Google client installed; the Drive fetch only runs when
it is actually needed and the credentials are present.

Results are cached per process (a render resolves each asset once,
and a beat rarely references the same asset twice).
"""
import os

_cache = {}


def fetch_asset_text(drive_rel_path, root_folder_id=None):
    """Download one asset file from Drive by its path relative to the
    `assets/` folder (e.g. "landmarks/eiffel-tower.svg"). The `assets`
    folder is found under the Drive root (DRIVE_FOLDER_ID), then the
    category subfolders are walked by path. Returns the file's text.
    Raises ValueError when the folder or file is not found, and
    RuntimeError when no Drive credentials are configured. A leading
    "assets/" in the path is tolerated, so a catalog entry written
    with the full root-relative path still resolves.
    """
    root = root_folder_id or os.environ.get("DRIVE_FOLDER_ID")
    if not root:
        raise RuntimeError(
            "no Drive folder configured: set DRIVE_FOLDER_ID")
    parts = [p for p in drive_rel_path.split("/") if p]
    if parts and parts[0] == "assets":
        parts = parts[1:]
    if not parts:
        raise ValueError("empty Drive path")
    key = (root, "/".join(parts))
    if key in _cache:
        return _cache[key]
    # Lazy import: googleapiclient is only needed when a Drive fetch
    # actually happens (in GitHub Actions, where drive.txt is
    # installed), not at import time.
    from pipeline.drive import video_env as env  # noqa: PLC0415

    service = env.drive_service()
    folder_id = env.find_folder(service, "assets", root)
    if folder_id is None:
        raise ValueError(
            "Drive folder 'assets' not found under the pack root; "
            "the pack has not been synced to Drive yet")
    for name in parts[:-1]:
        folder_id = env.find_folder(service, name, folder_id)
        if folder_id is None:
            raise ValueError(
                "Drive folder %r not found under assets/ "
                "(path %r)" % (name, drive_rel_path))
    raw = env.download_bytes(service, folder_id, parts[-1])
    if raw is None:
        raise ValueError(
            "asset file %r not found on Drive" % drive_rel_path)
    text = raw.decode("utf-8")
    _cache[key] = text
    return text


def clear_cache():
    """Drop the per-process fetch cache (tests only)."""
    _cache.clear()
