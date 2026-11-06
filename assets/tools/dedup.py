#!/usr/bin/env python3
"""Find duplicate SVGs across a directory.

Detection, cheapest first (report section 8):
  (a) exact file hash -- SHA-256 of the file bytes;
  (b) normalised-SVG hash -- strip metadata/comments/ids, sort
      attributes, round path coordinates to 2 decimals, then SHA-256;
  (c) path-data hash -- concatenate all d attributes, strip
      transforms, normalise numbers, then SHA-256.

Rendered perceptual hash (pHash) IS implemented here as step (d),
because a headless render is available on this VM: headless
Chromium (Chrome for Testing, ~/workspace/chrome-test/...). Each
SVG is screenshotted at 256x256 ink-on-white and reduced to a 64-bit
gradient hash (dHash) with Pillow; Hamming distance <= 5 groups two
files as near-identical renders. pHash is the WEAKEST signal and is
only ever a candidate for human review: two different line drawings
can hash close, so a pHash group never auto-deletes anything (this
tool never deletes). Pass --no-phash to skip the render step on
large directories (one Chromium screenshot per file, ~1s each).
No resvg / cairosvg / imagehash is installed; if one appears, it
would be a faster replacement for the Chromium step.

Usage: dedup.py <dir> [--catalog catalog.json] [--out report.json]
       [--no-phash]

Winner per group, tie-break in order:
  1. pack-safe licence first (CC0 > MIT / Apache-2.0 / ISC > CC-BY >
     CC-BY-SA > anything else / unknown);
  2. true-stroke beats filled beats silhouette (draw_on yes, then
     style_family line / geometric-line first);
  3. original source beats aggregator mirror (FreeSVG and SVG Repo
     are mirrors/indexes; anything else is treated as the original);
  4. cleaner file wins: fewer paths, then smaller file.

Licence/style info comes from the catalog when one is found
(--catalog, or assets/catalog.json above the scanned directory);
otherwise the tie-break notes the info as unknown and falls back to
cleanliness only. Losers are NOT deleted -- they are listed in the
report so a human can quarantine them.

Usage: dedup.py <dir> [--catalog catalog.json] [--out report.json]
Output (stdout, and --out if given):
  {"groups": [{"method": "exact|normalised|path-data",
               "files": [...], "winner": "...", "reason": "..."}],
   "phash": "skipped -- ..."}
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

_NUM_RE = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_LICENCE_RANK = {"CC0-1.0": 0, "CC0": 0, "public domain": 0,
                 "MIT": 1, "Apache-2.0": 1, "ISC": 1,
                 "CC-BY-4.0": 2, "CC-BY-3.0": 2, "CC-BY": 2,
                 "CC-BY-SA-4.0": 3, "CC-BY-SA-3.0": 3, "CC-BY-SA": 3}
_MIRROR_LIBRARIES = {"freesvg", "svg repo", "svgrepo", "svg nexus",
                     "noun project"}
_STYLE_RANK = {"line": 0, "geometric-line": 0, "doodle": 1,
               "flat": 2, "silhouette": 3}


def _round_numbers(text):
    """Round every decimal number in text to 2dp, dropping trailing
    zeros, so 1.234 and 1.23 hash the same."""
    def repl(m):
        try:
            v = round(float(m.group(0)), 2)
        except ValueError:
            return m.group(0)
        s = ("%.2f" % v).rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return _NUM_RE.sub(repl, text)


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _canonical_tree(root):
    """Canonical string for the normalised hash: local tag names,
    sorted attributes (ids, metadata and comments dropped), numbers
    rounded to 2dp."""
    parts = []

    def walk(el):
        if _local(el.tag) == "metadata":
            return  # metadata/comments are not the drawing
        attrs = []
        for k, v in sorted(el.attrib.items()):
            lk = _local(k)
            if lk in ("id",):
                continue
            attrs.append("%s=%s" % (lk, _round_numbers(v)))
        parts.append("<%s %s>" % (_local(el.tag), " ".join(attrs)))
        for child in el:
            walk(child)
        if el.text and el.text.strip():
            parts.append(_round_numbers(el.text.strip()))
    walk(root)
    return "".join(parts)


def _hashes(path):
    """Return (exact, normalised, path-data) hex digests for one file,
    plus the path count. Raises on unparseable XML."""
    with open(path, "rb") as f:
        raw = f.read()
    exact = hashlib.sha256(raw).hexdigest()
    root = ET.fromstring(raw)
    normalised = hashlib.sha256(
        _canonical_tree(root).encode("utf-8")).hexdigest()
    d_parts = []
    n_paths = 0
    for el in root.iter():
        if _local(el.tag) == "path":
            n_paths += 1
        d = el.get("d")
        if d:
            d_parts.append(_round_numbers(d))
    path_hash = hashlib.sha256(
        "|".join(d_parts).encode("utf-8")).hexdigest()
    return exact, normalised, path_hash, n_paths


def _load_catalog(path):
    """Return {file_basename_or_path: entry} for tie-break info, or
    {} when no catalog is available."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    assets = data.get("assets", data) if isinstance(data, dict) else data
    out = {}
    for entry in assets if isinstance(assets, list) else []:
        f = entry.get("file", "")
        out[os.path.basename(f)] = entry
        out[f] = entry
    return out


def _find_catalog(scan_dir):
    """assets/catalog.json above the scanned directory, if present."""
    d = os.path.abspath(scan_dir)
    while True:
        cand = os.path.join(d, "catalog.json")
        if os.path.exists(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _winner(files, catalog, path_counts, sizes):
    """Pick the winner file and explain why. Returns (winner, reason).
    Licence/style info comes from the catalog; unknown when absent."""
    def key(path):
        name = os.path.basename(path)
        entry = catalog.get(name) or catalog.get(path) or {}
        lic = entry.get("license", "")
        lic_rank = _LICENCE_RANK.get(lic, 9)
        draw_on = str(entry.get("draw_on", "")).lower() in ("yes", "true")
        style = _STYLE_RANK.get(entry.get("style_family", ""), 9)
        lib = str(entry.get("source_library", "")).lower()
        mirror = 1 if lib in _MIRROR_LIBRARIES else 0
        return (lic_rank, 0 if draw_on else 1, style, mirror,
                path_counts.get(path, 0), sizes.get(path, 0))

    ranked = sorted(files, key=key)
    win = ranked[0]
    entry = catalog.get(os.path.basename(win)) or {}
    bits = []
    if entry.get("license"):
        bits.append("licence %s (pack-safest in the group)"
                    % entry["license"])
    if entry.get("draw_on"):
        bits.append("draw_on=%s, style %s"
                    % (entry.get("draw_on"), entry.get("style_family")))
    if entry.get("source_library"):
        bits.append("source %s" % entry["source_library"])
    bits.append("%d paths, %d bytes (cleanest)"
                % (path_counts.get(win, 0), sizes.get(win, 0)))
    if not entry:
        bits = ["no catalog entry for any file in the group "
                "(licence/style unknown); cleanest file wins: "
                "%d paths, %d bytes"
                % (path_counts.get(win, 0), sizes.get(win, 0))]
    return win, "; ".join(bits)


def _find_chromium():
    for name in ("chromium", "chromium-browser", "google-chrome",
                 "chrome"):
        p = shutil.which(name)
        if p:
            return p
    home = os.path.expanduser("~")
    for cand in sorted(glob.glob(os.path.join(
            home, "workspace", "chrome-test", "browsers", "chrome",
            "*", "chrome-linux64", "chrome"))):
        if os.path.exists(cand):
            return cand
    return None


def _dhash(png_path):
    """64-bit gradient hash of a PNG: 9x8 greyscale, one bit per
    horizontal neighbour comparison (left brighter than right)."""
    from PIL import Image
    img = Image.open(png_path).convert("L").resize(
        (9, 8), Image.LANCZOS)
    px = list(img.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if px[y * 9 + x] > px[y * 9 + x + 1]
                                  else 0)
    return bits


def _render_hashes(chrome, files):
    """Screenshot each SVG at 256x256 ink-on-white via headless
    Chromium and return {path: dhash int}. Files that fail to render
    are skipped with a warning."""
    hashes = {}
    with tempfile.TemporaryDirectory() as tmp:
        for path in files:
            try:
                with open(path) as f:
                    svg = f.read()
            except OSError:
                continue
            svg = (svg.replace("{{ink}}", "#1c1c1c")
                      .replace("{{red}}", "#d9481f")
                      .replace("{{blue}}", "#2b5ea7"))
            html = ("<!doctype html><html><head><meta charset='utf-8'>"
                    "<style>*{margin:0;padding:0}body{width:256px;"
                    "height:256px;background:#fff;display:flex;"
                    "align-items:center;justify-content:center}"
                    "svg{width:240px;height:240px}</style></head>"
                    "<body>%s</body></html>" % svg)
            page = os.path.join(tmp, "page.html")
            png = os.path.join(tmp, "shot.png")
            with open(page, "w") as f:
                f.write(html)
            try:
                r = subprocess.run(
                    [chrome, "--headless", "--no-sandbox",
                     "--disable-gpu", "--hide-scrollbars",
                     "--force-device-scale-factor=1",
                     "--window-size=256,256",
                     "--screenshot=" + png, "file://" + page],
                    capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and os.path.exists(png):
                    hashes[path] = _dhash(png)
                else:
                    print("WARNING: pHash render failed for %s"
                          % path, file=sys.stderr)
            except (subprocess.TimeoutExpired, OSError) as e:
                print("WARNING: pHash render failed for %s: %s"
                      % (path, e), file=sys.stderr)
    return hashes


def _phash_groups(hashes, max_distance=5):
    """Union-find over dHash values: Hamming distance <= 5 means a
    near-identical render. Returns a list of file groups (size >= 2)."""
    paths = sorted(hashes)
    parent = {p: p for p in paths}

    def find(p):
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if bin(hashes[a] ^ hashes[b]).count("1") <= max_distance:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
    groups = {}
    for p in paths:
        groups.setdefault(find(p), []).append(p)
    return [sorted(g) for g in groups.values() if len(g) >= 2]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dir", help="directory of SVGs to scan")
    p.add_argument("--catalog", default=None,
                   help="catalog.json for licence/style tie-breaks")
    p.add_argument("--out", default=None,
                   help="also write the JSON report to this file")
    p.add_argument("--no-phash", action="store_true",
                   help="skip the rendered-pHash step (slow on large "
                        "directories: one Chromium screenshot per file)")
    args = p.parse_args(argv)

    scan_dir = args.dir
    files = sorted(
        os.path.join(scan_dir, f) for f in os.listdir(scan_dir)
        if f.lower().endswith(".svg"))
    if not files:
        print("no .svg files in %s" % scan_dir, file=sys.stderr)
        return 1

    catalog_path = args.catalog or _find_catalog(scan_dir)
    catalog = _load_catalog(catalog_path)
    if catalog_path:
        print("tie-break info from %s (%d entries)"
              % (catalog_path, len(catalog) // 2 or len(catalog)),
              file=sys.stderr)
    else:
        print("no catalog found: licence/style tie-breaks are unknown",
              file=sys.stderr)

    buckets = {"exact": {}, "normalised": {}, "path-data": {}}
    path_counts, sizes = {}, {}
    for path in files:
        try:
            exact, norm, phash, n_paths = _hashes(path)
        except ET.ParseError as e:
            print("WARNING: skipping unparseable %s: %s"
                  % (path, e), file=sys.stderr)
            continue
        buckets["exact"].setdefault(exact, []).append(path)
        buckets["normalised"].setdefault(norm, []).append(path)
        buckets["path-data"].setdefault(phash, []).append(path)
        path_counts[path] = n_paths
        sizes[path] = os.path.getsize(path)

    groups = []
    seen_sets = set()
    # strongest method first; a file set already reported under a
    # stronger method is not reported again under a weaker one.
    for method in ("exact", "normalised", "path-data"):
        for digest, members in sorted(buckets[method].items()):
            if len(members) < 2:
                continue
            key = tuple(sorted(members))
            if key in seen_sets:
                continue
            seen_sets.add(key)
            winner, reason = _winner(members, catalog, path_counts,
                                     sizes)
            groups.append({"method": method,
                           "files": sorted(members),
                           "winner": winner,
                           "reason": reason})
    # (d) rendered pHash -- weakest signal, candidates for human
    # review only. Runs last; a set already reported under a stronger
    # method is not reported again.
    phash_note = None
    if args.no_phash:
        phash_note = "skipped -- --no-phash given"
    else:
        chrome = _find_chromium()
        if not chrome:
            phash_note = ("skipped -- no renderer available "
                          "(no resvg, cairosvg, imagehash, or "
                          "headless Chromium found)")
        else:
            print("pHash: rendering %d SVGs with %s ..."
                  % (len(files), chrome), file=sys.stderr)
            hashes = _render_hashes(chrome, files)
            for members in _phash_groups(hashes):
                key = tuple(sorted(members))
                if key in seen_sets:
                    continue
                seen_sets.add(key)
                winner, reason = _winner(members, catalog,
                                         path_counts, sizes)
                groups.append({
                    "method": "phash",
                    "files": sorted(members),
                    "winner": winner,
                    "reason": "near-identical renders (dHash Hamming "
                              "distance <= 5); human-review candidate "
                              "only -- " + reason})
            phash_note = ("rendered with headless Chromium, dHash "
                          "Hamming distance <= 5")
    report = {
        "groups": groups,
        "phash": phash_note,
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
