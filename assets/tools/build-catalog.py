#!/usr/bin/env python3
"""Validate assets/catalog.json and generate LICENSES.md + catalog.csv.

Validates:
  - every .svg under the assets dir (excluding staging/, sources/,
    tools/) has a catalog entry, and every catalog entry points at
    a file that exists;
  - no duplicate catalog ids;
  - all required fields present on every entry: id, title, category,
    file, source_library, source_url, license, attribution_required,
    redistribution_allowed, status, style_family, draw_on, viewBox;
  - viewBox parses as four numbers;
  - aspect_ratio (when present) matches the viewBox (width/height,
    within 0.01).

Generates, from the catalog (the catalog is the source of truth):
  - assets/LICENSES.md -- per-library licence list + attribution
    texts. The pack is a collection with per-file licences; no
    single licence covers the whole pack.
  - assets/catalog.csv -- one row per asset, same fields as the
    catalog entries (tags joined with ";").

Usage:
  build-catalog.py --catalog assets/catalog.json --assets-dir assets
Exit non-zero with clear errors on any failure; nothing is generated
until validation passes.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter

REQUIRED = ["id", "title", "category", "file", "source_library",
            "source_url", "license", "attribution_required",
            "redistribution_allowed", "status", "style_family",
            "draw_on", "viewBox"]
OPTIONAL = ["tags", "source_author", "license_url", "attribution_text",
            "share_alike", "original_file", "duplicates_of", "aliases",
            "added_in", "aspect_ratio", "has_text", "has_raster",
            "stroke_width_original", "notes"]
EXCLUDE_DIRS = {"staging", "sources", "tools"}


def _load_catalog(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        assets = data.get("assets")
        if not isinstance(assets, list):
            raise ValueError("catalog.json has no top-level 'assets' list")
        return data, assets
    if isinstance(data, list):
        return {"assets": data}, data
    raise ValueError("catalog.json must be an object with an 'assets' "
                     "list, or a plain list")


def _parse_viewbox(value):
    try:
        parts = [float(x) for x in str(value).split()]
    except ValueError:
        return None
    return parts if len(parts) == 4 else None


def validate(catalog_path, assets_dir):
    """Return (data, assets, errors). errors is a list of strings."""
    errors = []
    try:
        data, assets = _load_catalog(catalog_path)
    except (OSError, ValueError) as e:
        return None, [], ["cannot load catalog %s: %s"
                          % (catalog_path, e)]
    # Catalog 'file' paths are relative to the assets dir -- the
    # Drive `assets/` folder (e.g. "landmarks/eiffel-tower.svg").
    # The local final layout mirrors it: <assets-dir>/landmarks/...
    assets_dir = os.path.abspath(assets_dir)

    seen_ids = Counter()
    catalog_files = {}
    for i, entry in enumerate(assets):
        where = "assets[%d]" % i
        if not isinstance(entry, dict):
            errors.append("%s is not an object" % where)
            continue
        for field in REQUIRED:
            if field not in entry or entry[field] in (None, ""):
                errors.append("%s (id=%s) is missing required field %r"
                              % (where, entry.get("id", "?"), field))
        asset_id = entry.get("id")
        if asset_id:
            seen_ids[asset_id] += 1
            where = "asset %s" % asset_id
        f = entry.get("file", "")
        if f:
            catalog_files[os.path.normpath(f)] = asset_id or "?"
            full = os.path.join(assets_dir, f)
            if not os.path.exists(full):
                errors.append("%s: file %r does not exist" % (where, f))
        vb = _parse_viewbox(entry.get("viewBox", ""))
        if vb is None:
            errors.append("%s: viewBox %r does not parse as four "
                          "numbers" % (where, entry.get("viewBox")))
        elif entry.get("aspect_ratio") not in (None, ""):
            try:
                ar = float(entry["aspect_ratio"])
                expect = vb[2] / vb[3] if vb[3] else 0
                if abs(ar - expect) > 0.01:
                    errors.append(
                        "%s: aspect_ratio %s does not match viewBox "
                        "%s (width/height = %.2f)"
                        % (where, entry["aspect_ratio"],
                           entry.get("viewBox"), expect))
            except ValueError:
                errors.append("%s: aspect_ratio %r is not a number"
                              % (where, entry["aspect_ratio"]))
    for asset_id, n in seen_ids.items():
        if n > 1:
            errors.append("duplicate catalog id %r (%d entries)"
                          % (asset_id, n))

    # every .svg on disk must have an entry, and vice versa
    on_disk = set()
    for dirpath, dirnames, filenames in os.walk(assets_dir):
        rel_dir = os.path.relpath(dirpath, assets_dir)
        top = rel_dir.split(os.sep)[0] if rel_dir != "." else ""
        if top in EXCLUDE_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if not (rel_dir == "." and d in EXCLUDE_DIRS)]
        for name in filenames:
            if name.lower().endswith(".svg"):
                full = os.path.join(dirpath, name)
                on_disk.add(os.path.normpath(
                    os.path.relpath(full, assets_dir)))
    for f in sorted(on_disk - set(catalog_files)):
        errors.append("file %s has no catalog entry" % f)
    for f in sorted(set(catalog_files) - on_disk):
        errors.append("catalog entry %s points at %s, which is not "
                      "under %s" % (catalog_files[f], f, assets_dir))
    return data, assets, errors


def _licenses_md(data, assets):
    lines = ["# Licences",
             "",
             "Per-library licences for the asset pack. The pack is a "
             "collection: each file keeps its own licence (see the "
             "catalog entry for the file). No single licence covers "
             "the whole pack.",
             "",
             "Pack: %s, version %s"
             % (data.get("pack", "?"), data.get("version", "?")),
             ""]
    by_lib = {}
    for entry in assets:
        by_lib.setdefault(entry.get("source_library", "?"), []).append(
            entry)
    for lib in sorted(by_lib):
        entries = by_lib[lib]
        licences = sorted({e.get("license", "?") for e in entries})
        lines.append("## %s" % lib)
        lines.append("")
        lines.append("- Licence: %s" % ", ".join(licences))
        urls = sorted({e.get("license_url", "") for e in entries
                       if e.get("license_url")})
        if urls:
            lines.append("- Licence text: %s" % ", ".join(urls))
        src_urls = sorted({e.get("source_url", "") for e in entries
                           if e.get("source_url")})
        if src_urls:
            lines.append("- Source: %s" % ", ".join(src_urls[:5]))
        need_attr = [e for e in entries
                     if e.get("attribution_required")]
        lines.append("- Files: %d; attribution required: %s"
                     % (len(entries),
                        "yes (%d files)" % len(need_attr)
                        if need_attr else "no"))
        for e in need_attr:
            text = e.get("attribution_text") or \
                "Attribution required (see catalog entry %s)." % e["id"]
            lines.append("  - %s (%s): %s" % (e["id"], e["license"],
                                              text))
        lines.append("")
    return "\n".join(lines)


def _write_csv(assets, path):
    fields = REQUIRED + ["aspect_ratio", "tags", "source_author",
                         "license_url", "attribution_text", "share_alike"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for entry in assets:
            row = dict(entry)
            tags = row.get("tags")
            row["tags"] = ";".join(tags) if isinstance(tags, list) \
                else (tags or "")
            for k in ("attribution_required", "redistribution_allowed",
                      "share_alike"):
                if k in row:
                    row[k] = str(row[k]).lower()
            w.writerow(row)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", required=True,
                   help="assets/catalog.json")
    p.add_argument("--assets-dir", required=True,
                   help="assets dir holding the normalised SVGs")
    args = p.parse_args(argv)

    data, assets, errors = validate(args.catalog, args.assets_dir)
    if errors:
        print("catalog validation FAILED (%d error(s)):"
              % len(errors), file=sys.stderr)
        for e in errors:
            print("  - %s" % e, file=sys.stderr)
        return 1
    print("catalog OK: %d assets" % len(assets))

    licenses_path = os.path.join(args.assets_dir, "LICENSES.md")
    with open(licenses_path, "w") as f:
        f.write(_licenses_md(data, assets))
    print("wrote %s" % licenses_path)
    csv_path = os.path.join(args.assets_dir, "catalog.csv")
    _write_csv(assets, csv_path)
    print("wrote %s" % csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
