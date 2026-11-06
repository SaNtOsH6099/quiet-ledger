#!/usr/bin/env python3
"""Merge the per-library partial catalogs into the final pack catalog.

Steps:
  1. Load every catalog-<library>.json under the assets dir.
  2. Cross-library dedup (hash-based, via dedup.py): exact file hash,
     then normalised-SVG hash. For each duplicate group, keep the
     winner (tie-break: pack-safe licence > true-stroke > original
     source > cleaner file) and record the loser ids in the winner's
     duplicates_of. Losers are dropped from the final catalog and
     their staged files are NOT copied to the final layout.
     Path-data-only matches (same paths, different viewBox/colours)
     are reported for review but NOT auto-deduped -- they may be
     distinct artwork.
  3. Place winners into the final layout: assets/<category>/<id>.svg,
     where <id> is the catalog id with ':' and '_' replaced by '-'
     (guaranteed unique, since catalog ids are unique).
  4. Rewrite catalog fields for the Drive hybrid:
       file: <category>/<id>.svg            (relative to Drive assets/)
       original_file: sources/<lib>/...     (relative to Drive assets/)
  5. Prune sources/: originals not referenced by any kept entry's
     original_file are moved to ~/workspace/asset-pack-rejected/<lib>/
     (recoverable, out of the repo) so the Drive sync only uploads
     kept assets' originals.
  6. Write assets/catalog.json (pack ink-paper-asset-pack, version
     2026.11.0, palette, assets sorted by id). Validate afterwards
     with build-catalog.py (which also generates LICENSES.md + csv).

Usage:
  merge.py [--assets-dir assets] [--reject-dir ~/workspace/asset-pack-rejected]
           [--dry-run]
  --dry-run: report what would change without writing or moving anything.
"""
import argparse
import glob
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dedup as dedup_mod  # noqa: E402

PACK = "ink-paper-asset-pack"
VERSION = "2026.11.0"
PALETTE = {"paper": "#f6f1e7", "ink": "#1c1c1c",
           "red": "#d9481f", "blue": "#2b5ea7"}
REQUIRED = ["id", "title", "category", "tags", "file", "original_file",
            "source_library", "source_url", "source_author", "license",
            "license_url", "attribution_required", "attribution_text",
            "share_alike", "redistribution_allowed", "status",
            "style_family", "draw_on", "viewBox", "duplicates_of",
            "added_in"]


def _id_filename(asset_id):
    return asset_id.replace(":", "-").replace("_", "-") + ".svg"


def _strip_assets_prefix(path):
    """'assets/staging/x.svg' -> 'staging/x.svg'; 'assets/sources/y'
    -> 'sources/y'. Leaves other paths alone."""
    if path.startswith("assets/"):
        return path[len("assets/"):]
    return path


def load_partials(assets_dir):
    """Return (entries, by_id) for every partial catalog."""
    entries = []
    for path in sorted(glob.glob(os.path.join(assets_dir,
                                              "catalog-*.json"))):
        with open(path) as f:
            data = json.load(f)
        lib_entries = data.get("assets", [])
        for e in lib_entries:
            e["_partial"] = os.path.basename(path)
            entries.append(e)
    ids = [e["id"] for e in entries]
    dup = [i for i in set(ids) if ids.count(i) > 1]
    if dup:
        raise ValueError("duplicate catalog ids across partials: %s"
                         % dup[:10])
    return entries, {e["id"]: e for e in entries}


def dedup_entries(entries, repo_root):
    """Hash-based cross-library dedup. Returns (kept, dropped, report)
    where dropped is {loser_id: (winner_id, method, reason)} and
    report lists path-data-only groups for review."""
    # Map staged file path -> entry, for the tie-break catalog.
    by_path = {}
    for e in entries:
        staged = os.path.join(repo_root, e["file"])
        by_path[staged] = e
        by_path[os.path.basename(e["file"])] = e
    catalog = {}
    for e in entries:
        catalog[os.path.basename(e["file"])] = e
        catalog[os.path.join(repo_root, e["file"])] = e

    hashes = {}
    for e in entries:
        staged = os.path.join(repo_root, e["file"])
        try:
            exact, normalised, path_hash, n_paths = \
                dedup_mod._hashes(staged)
        except Exception as exc:
            print("  !! cannot hash %s: %s" % (staged, exc))
            continue
        hashes[e["id"]] = {
            "exact": exact, "normalised": normalised,
            "path": path_hash, "n_paths": n_paths,
            "size": os.path.getsize(staged),
            "staged": staged,
        }

    dropped = {}
    # Group by exact hash, then by normalised hash (skip already grouped).
    grouped = set()
    for method in ("exact", "normalised"):
        groups = {}
        for asset_id, h in hashes.items():
            if asset_id in grouped:
                continue
            groups.setdefault(h[method], []).append(asset_id)
        for key, members in groups.items():
            if len(members) < 2:
                continue
            files = [hashes[m]["staged"] for m in members]
            path_counts = {hashes[m]["staged"]: hashes[m]["n_paths"]
                           for m in members}
            sizes = {hashes[m]["staged"]: hashes[m]["size"]
                     for m in members}
            winner_file, reason = dedup_mod._winner(
                files, catalog, path_counts, sizes)
            winner_id = next(m for m in members
                             if hashes[m]["staged"] == winner_file)
            for loser in members:
                if loser == winner_id:
                    continue
                dropped[loser] = (winner_id, method, reason)
                grouped.add(loser)
            grouped.add(winner_id)
    # Path-data-only groups: same paths, different normalised hash.
    # Report only; do not auto-dedup (may be distinct artwork).
    path_groups = {}
    for asset_id, h in hashes.items():
        if asset_id in dropped:
            continue
        path_groups.setdefault(h["path"], []).append(asset_id)
    path_report = []
    for key, members in path_groups.items():
        if len(members) < 2:
            continue
        # Only report when the normalised hashes differ (otherwise
        # they were already deduped above).
        if len({hashes[m]["normalised"] for m in members}) < 2:
            continue
        path_report.append(sorted(members))
    kept = [e for e in entries if e["id"] not in dropped]
    return kept, dropped, sorted(path_report)


def merge(assets_dir, reject_dir, dry_run=False):
    # Work in absolute paths throughout, so the prune comparison
    # (walked file vs catalog original_file) is apples-to-apples.
    assets_dir = os.path.abspath(assets_dir)
    # assets_dir is <repo>/assets, so the repo root is one level up.
    repo_root = os.path.dirname(assets_dir)
    entries, by_id = load_partials(assets_dir)
    print("loaded %d entries from partial catalogs" % len(entries))

    kept, dropped, path_report = dedup_entries(entries, repo_root)
    print("dedup: %d dropped, %d kept" % (len(dropped), len(kept)))
    for loser, (winner, method, reason) in sorted(dropped.items()):
        print("  drop %s -> %s (%s): %s"
              % (loser, winner, method, reason))
        win = by_id[winner]
        dups = list(win.get("duplicates_of") or [])
        if loser not in dups:
            dups.append(loser)
        win["duplicates_of"] = sorted(dups)
    if path_report:
        print("path-data-only groups (kept both, review):")
        for members in path_report:
            print("  %s" % ", ".join(members))

    # Final layout + field rewrite.
    final = []
    for e in sorted(kept, key=lambda x: x["id"]):
        filename = _id_filename(e["id"])
        category = e["category"]
        final_path = os.path.join(category, filename)
        # Collision check (id-derived names should be unique).
        if any(f["file"] == final_path for f in final):
            raise ValueError("filename collision: %s" % final_path)
        staged = os.path.join(repo_root, e["file"])
        dest = os.path.join(assets_dir, category, filename)
        e["file"] = final_path
        e["original_file"] = _strip_assets_prefix(
            e.get("original_file", ""))
        e.pop("_partial", None)
        for k in REQUIRED:
            if k not in e:
                raise ValueError("entry %s missing field %s"
                                 % (e["id"], k))
        final.append(e)
        if not dry_run:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(staged, dest)
    print("placed %d files into %s/<category>/" % (len(final), assets_dir))

    # Prune sources/: move unreferenced originals out of the repo.
    # Only .svg files are pruned; docs (LICENSE.md, README.md, etc.)
    # always stay. An original_file that is a directory (Open Peeps:
    # the figures are assembled from a parts collection) keeps every
    # file under it.
    kept_originals = set()
    for e in final:
        orig = e.get("original_file", "")
        if not orig:
            continue
        full = os.path.join(assets_dir, orig)
        if os.path.isdir(full):
            for dirpath, _d, filenames in os.walk(full):
                for name in filenames:
                    kept_originals.add(os.path.join(dirpath, name))
        else:
            kept_originals.add(full)
    moved = 0
    sources_dir = os.path.join(assets_dir, "sources")
    for dirpath, dirnames, filenames in os.walk(sources_dir):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if not name.lower().endswith(".svg"):
                continue
            if full in kept_originals:
                continue
            rel = os.path.relpath(full, sources_dir)
            dest = os.path.join(reject_dir, rel)
            if not dry_run:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(full, dest)
            moved += 1
    print("pruned %d unreferenced originals to %s" % (moved, reject_dir))

    catalog = {"pack": PACK, "version": VERSION,
               "palette": PALETTE, "assets": final}
    out_path = os.path.join(assets_dir, "catalog.json")
    if not dry_run:
        with open(out_path, "w") as f:
            json.dump(catalog, f, indent=2)
            f.write("\n")
    print("wrote %s (%d assets)" % (out_path, len(final)))
    return catalog, dropped, path_report


def main():
    parser = argparse.ArgumentParser(
        description="merge partial catalogs into assets/catalog.json")
    parser.add_argument("--assets-dir", default="assets")
    parser.add_argument("--reject-dir",
                        default=os.path.expanduser(
                            "~/workspace/asset-pack-rejected"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    merge(args.assets_dir, args.reject_dir, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
