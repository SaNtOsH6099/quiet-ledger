#!/usr/bin/env python3
"""Shared catalog access for the asset pack.

The catalog lives at <repo-root>/assets/catalog.json. Its path is
resolved from this file's location, never from the current working
directory, so it works from GitHub Actions, from Muse's local runs,
and from any cwd.

Test hook: set the ASSET_CATALOG environment variable to point at a
different catalog.json (used by the local end-to-end test with a
throwaway catalog in /tmp). Production never sets it.

Stdlib only.
"""
import json
import os

DEFAULT_PALETTE = {"ink": "#1c1c1c", "red": "#d9481f",
                   "blue": "#2b5ea7", "paper": "#f6f1e7"}

_cache = None
_cache_path = None


def repo_root():
    """Repo root: three levels up from pipeline/assets/catalog.py."""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def catalog_path():
    override = os.environ.get("ASSET_CATALOG")
    if override:
        return os.path.abspath(override)
    return os.path.join(repo_root(), "assets", "catalog.json")


def load_catalog():
    """Load catalog.json. Returns the parsed dict, or None when the
    file is missing or unreadable (a fresh checkout has no pack yet;
    callers that can proceed without assets treat None as 'no
    catalog', callers that must resolve a reference fail loudly)."""
    global _cache, _cache_path
    path = catalog_path()
    if _cache is not None and _cache_path == path:
        return _cache
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    _cache, _cache_path = data, path
    return data


def assets_by_id():
    """Return {asset id: entry} for the loaded catalog, or {} when
    there is no catalog."""
    data = load_catalog()
    if not data:
        return {}
    assets = data.get("assets", []) if isinstance(data, dict) else []
    return {e.get("id"): e for e in assets
            if isinstance(e, dict) and e.get("id")}


def asset_file_path(entry):
    """Resolve a catalog entry's 'file' to a real local path, for
    testing and for Muse's local pack copy. The catalog 'file' is the
    path relative to the Drive `assets/` folder (e.g.
    'landmarks/x.svg'), so the local candidates are tried under
    <repo>/assets/ first, then relative to the repo root and to the
    catalog file (for test catalogs outside the repo). Returns None
    when the file is not found locally -- the resolver then fetches
    it from Drive."""
    f = entry.get("file", "")
    if not f:
        return None
    if os.path.isabs(f) and os.path.exists(f):
        return f
    catalog_dir = os.path.dirname(catalog_path())
    for cand in (os.path.join(repo_root(), "assets", f),
                 os.path.join(repo_root(), f),
                 os.path.join(catalog_dir, f),
                 os.path.abspath(f)):
        if os.path.exists(cand):
            return cand
    return None
