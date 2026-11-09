#!/usr/bin/env python3
"""Sync the asset pack to Google Drive, idempotently.

The pack's asset files live on Drive, in the "svg assets" folder
under DRIVE_FOLDER_ID — not in this repo (the repo copy was deleted
in the 2026-11-09 clean). This module uploads a local pack directory
to Drive, mirroring its relative paths under that folder, and updates
files in place when they change. It is kept only for maintaining the
SVG pack; Echoes does not use the pack, and echoes-render never
calls this module.

Usage: sync_pack.py --pack-dir assets [--drive-subdir "svg assets"] [--dry-run]

  --pack-dir      local directory holding the pack files to upload
                  (the final normalised SVGs by category, plus
                  sources/ for provenance). Defaults to "assets".
  --drive-subdir  Drive folder under DRIVE_FOLDER_ID to mirror into.
                  Defaults to "svg assets", so a local
                  "assets/landmarks/eiffel-tower.svg" lands at
                  <DRIVE_FOLDER_ID>/svg assets/landmarks/eiffel-tower.svg.
  --dry-run       print what would change without uploading anything.

SVG files only: only .svg files are uploaded (the walk skips
everything else). The staging intermediates are also skipped
(--exclude staging), so only the final normalised SVGs and the
sources go up.

Idempotency: for each file, the existing Drive file's md5Checksum is
compared with the local file's md5. Identical files are skipped, so a
re-run after a small change only uploads the changed files. New files
are created, changed files are updated in place (same Drive file id,
so links do not break), and files deleted locally are NOT deleted on
Drive (deletion is a deliberate, separate step -- a sync must never
wipe the pack because of a bad local checkout).

Needs the Drive secrets (DRIVE_OAUTH_JSON / DRIVE_FOLDER_ID). No
service account: a service account has no storage quota and cannot
create files in a personal Drive folder.
"""
import argparse
import hashlib
import os
import ssl
import sys
import time

from pipeline.drive import video_env as env


def _is_transient(exc):
    """True when a Drive failure is worth rebuilding the service and
    retrying: an SSL/network failure (including the token-refresh
    ssl.SSLEOFError that kills a sync after ~1 hour, when the
    long-lived HTTP connection goes stale), an auth refresh /
    401/403 failure, or a transient server-side failure (429 rate
    limit, or 5xx such as a 503 Service Unavailable during a
    resumable upload). Anything else (a bad file, a bad path, a
    programming error) is not transient and must fail loudly."""
    if isinstance(exc, ssl.SSLError):
        return True
    try:
        from google.auth.exceptions import RefreshError
        if isinstance(exc, RefreshError):
            return True
    except ImportError:
        pass
    try:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError) and exc.resp.status in (401, 403, 429, 500, 502, 503, 504):
            return True
    except ImportError:
        pass
    return isinstance(exc, OSError)


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _drive_md5(service, file_id):
    """The md5Checksum of a Drive file, or None when Drive has none
    (Google-native files have no md5; pack files are plain uploads,
    so they always have one)."""
    try:
        meta = service.files().get(
            fileId=file_id, fields="md5Checksum").execute()
    except Exception:
        return None
    return meta.get("md5Checksum")


def _ensure_folder(service, parent_id, rel_dir, cache):
    """Find or create the Drive folder for rel_dir, relative to
    parent_id ("" = parent_id itself). Returns its folder id.
    Results are cached per path in `cache`."""
    if rel_dir in cache:
        return cache[rel_dir]
    folder_id = parent_id
    walked = []
    for name in [p for p in rel_dir.split("/") if p]:
        walked.append(name)
        key = "/".join(walked)
        if key in cache:
            folder_id = cache[key]
            continue
        folder_id = env.find_or_create_folder(service, name, folder_id)
        cache[key] = folder_id
    cache[rel_dir] = folder_id
    return folder_id


def sync_pack(pack_dir, drive_subdir, dry_run=False, exclude=()):
    """Upload pack_dir to Drive under drive_subdir. Returns
    (new, updated, unchanged) counts. `exclude` is a list of path
    prefixes (relative to pack_dir) to skip, e.g. ["staging",
    "tools", "catalog-"] -- anything whose relative path starts with
    one of them is not uploaded. Only the asset files and the
    sources go up; the catalog and tools are not in this repo.

    Token resilience: the Drive access token lives ~1 hour, and a
    sync of the whole pack takes longer. The refresh that fires when
    the token expires can fail (ssl.SSLEOFError on the stale
    long-lived connection) and kill the run. So the service is
    rebuilt proactively every 800 files (a fresh token on a fresh
    connection, well inside the token's life), and every Drive call
    is retried -- rebuilding the service first -- on a transient
    failure. The folder cache holds Drive folder ids, which are
    stable across a rebuild, so it survives.
    """
    service = env.drive_service()
    root = os.environ.get("DRIVE_FOLDER_ID")
    if not root:
        raise RuntimeError("no Drive folder: set DRIVE_FOLDER_ID")
    folder_cache = {}
    files_since_rebuild = [0]

    def _call(fn):
        """Run fn(service); on a transient Drive failure, rebuild
        the service and retry (up to 5 times, with backoff)."""
        nonlocal service
        for attempt in range(6):
            try:
                return fn(service)
            except Exception as exc:
                if not _is_transient(exc) or attempt == 5:
                    raise
                print(f"  ! transient Drive error ({exc!r}); "
                      f"rebuilding service, retry {attempt + 1}/5")
                time.sleep(min(2 ** attempt, 30))
                service = env.drive_service()
                files_since_rebuild[0] = 0
        raise RuntimeError("unreachable")

    def _maybe_rebuild():
        # Proactive rebuild: a fresh token on a fresh connection
        # before the ~1-hour token can expire mid-upload.
        nonlocal service
        if files_since_rebuild[0] >= 800:
            service = env.drive_service()
            files_since_rebuild[0] = 0

    base_id = _call(
        lambda s: _ensure_folder(s, root, drive_subdir, folder_cache))
    new, updated, unchanged = 0, 0, 0
    for dirpath, dirnames, filenames in os.walk(pack_dir):
        rel_dir = os.path.relpath(dirpath, pack_dir)
        if rel_dir == ".":
            rel_dir = ""
        # Prune excluded directories (and the pack's own staging).
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in ("__pycache__",)
            and not any((os.path.join(rel_dir, d) if rel_dir else d)
                        .startswith(p) for p in exclude))
        folder_id = _call(
            lambda s: _ensure_folder(s, base_id, rel_dir, folder_cache))
        for name in sorted(filenames):
            # SVG files only.
            if not name.lower().endswith(".svg"):
                continue
            rel_path = os.path.join(rel_dir, name) if rel_dir else name
            if any(rel_path.startswith(p) for p in exclude):
                continue
            local_path = os.path.join(dirpath, name)
            _maybe_rebuild()
            existing = _call(
                lambda s: env.find_file(s, name, folder_id))
            if existing:
                if _call(lambda s: _drive_md5(s, existing)) == \
                        _md5(local_path):
                    unchanged += 1
                    print(f"  = {rel_path} (unchanged)")
                    files_since_rebuild[0] += 1
                    continue
                if dry_run:
                    print(f"  ~ {rel_path} (would update)")
                    updated += 1
                    files_since_rebuild[0] += 1
                    continue
                _call(lambda s: env.upload_file(
                    s, folder_id, local_path, name))
                updated += 1
                print(f"  ~ {rel_path} (updated)")
            else:
                if dry_run:
                    print(f"  + {rel_path} (would upload)")
                    new += 1
                    files_since_rebuild[0] += 1
                    continue
                _call(lambda s: env.upload_file(
                    s, folder_id, local_path, name))
                new += 1
                print(f"  + {rel_path} (new)")
            files_since_rebuild[0] += 1
    return new, updated, unchanged


def main():
    parser = argparse.ArgumentParser(
        description="sync the asset pack to Drive (idempotent)")
    parser.add_argument("--pack-dir", default="assets")
    parser.add_argument("--drive-subdir", default="svg assets")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", action="append", default=[],
                        help="relative-path prefix to skip (repeatable), "
                             "e.g. --exclude staging --exclude tools "
                             "--exclude catalog-")
    args = parser.parse_args()
    if not os.path.isdir(args.pack_dir):
        print(f"pack dir {args.pack_dir!r} not found", file=sys.stderr)
        return 2
    new, updated, unchanged = sync_pack(
        args.pack_dir, args.drive_subdir, dry_run=args.dry_run,
        exclude=args.exclude)
    print(f"sync {'(dry run) ' if args.dry_run else ''}done: "
          f"{new} new, {updated} updated, {unchanged} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
