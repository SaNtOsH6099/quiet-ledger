#!/usr/bin/env python3
"""Render a visual QA preview PNG for every asset in the catalog.

Each asset is drawn on the house paper #f6f1e7 at 1080x1920
(asset centred, scaled to fit with margins), with the {{ink}} /
{{red}} / {{blue}} placeholders substituted for the real palette,
and saved as a PNG in the output dir.

Renderer, first one that works on this machine:
  1. resvg (binary on PATH) -- not present on this VM;
  2. cairosvg (Python module) -- not installed on this VM;
  3. headless Chromium -- FOUND on this VM at
     ~/workspace/chrome-test/browsers/chrome/.../chrome-linux64/chrome
     (Chrome for Testing 155, installed for the video pipeline).
     Used via --headless --screenshot, one page per asset.
If none of the three is available, nothing is installed: the tool
falls back to verifying with Pillow that every SVG parses and has a
viewBox, writes preview-report.json saying visual rendering was
not possible, and exits 0 (verification done, no PNGs).

Usage:
  render-preview.py --catalog assets/catalog.json --out <dir>
      [--limit N]
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

PAPER = "#f6f1e7"
DEFAULT_PALETTE = {"ink": "#1c1c1c", "red": "#d9481f",
                   "blue": "#2b5ea7", "paper": "#f6f1e7"}
CANVAS_W, CANVAS_H = 1080, 1920
MARGIN = 120  # asset fits inside 840 x 1680


def _load_catalog(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data, data.get("assets", [])
    return {}, data


def _resolve_file(entry, catalog_path):
    """Catalog 'file' paths are relative to the assets dir (the Drive
    `assets/` folder, e.g. "landmarks/eiffel-tower.svg"). Fall back
    to relative to the repo root (old convention) and to the catalog
    file, for test catalogs outside the repo."""
    f = entry.get("file", "")
    assets_dir = os.path.dirname(os.path.abspath(catalog_path))
    repo_root = os.path.dirname(assets_dir)
    for cand in (os.path.join(assets_dir, f),
                 os.path.join(repo_root, f),
                 os.path.join(repo_root, "assets", f),
                 os.path.abspath(f)):
        if os.path.exists(cand):
            return cand
    return None


def _viewbox(svg_text):
    try:
        root = ET.fromstring(svg_text.encode("utf-8"))
    except ET.ParseError:
        return None
    vb = root.get("viewBox")
    if not vb:
        return None
    try:
        parts = [float(x) for x in vb.split()]
    except ValueError:
        return None
    return parts if len(parts) == 4 else None


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


def _render_chromium(chrome, svg_text, vb, out_png):
    """One headless-Chromium screenshot of the SVG on paper."""
    w = vb[2] * min((CANVAS_W - 2 * MARGIN) / vb[2],
                    (CANVAS_H - 2 * MARGIN) / vb[3])
    h = vb[3] * min((CANVAS_W - 2 * MARGIN) / vb[2],
                    (CANVAS_H - 2 * MARGIN) / vb[3])
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<style>*{margin:0;padding:0}body{width:1080px;height:1920px;"
            "background:%s;display:flex;align-items:center;"
            "justify-content:center}div{width:%.0fpx;height:%.0fpx}"
            "svg{width:100%%;height:100%%;display:block}</style></head>"
            "<body><div>%s</div></body></html>"
            % (PAPER, w, h, svg_text))
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "page.html")
        with open(page, "w") as f:
            f.write(html)
        cmd = [chrome, "--headless", "--no-sandbox", "--disable-gpu",
               "--hide-scrollbars", "--force-device-scale-factor=1",
               "--window-size=1080,1920",
               "--screenshot=" + out_png, "file://" + page]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=120)
        if r.returncode != 0 or not os.path.exists(out_png):
            raise RuntimeError("chromium screenshot failed: %s"
                               % (r.stderr or r.stdout)[:300])
    return out_png


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)

    data, assets = _load_catalog(args.catalog)
    if args.limit:
        assets = assets[:args.limit]
    palette = dict(DEFAULT_PALETTE)
    palette.update(data.get("palette", {}) or {})
    # catalog palette may use 'paper' too; only ink/red/blue are
    # placeholders in the SVGs.
    subs = {"{{ink}}": palette.get("ink", DEFAULT_PALETTE["ink"]),
            "{{red}}": palette.get("red", DEFAULT_PALETTE["red"]),
            "{{blue}}": palette.get("blue", DEFAULT_PALETTE["blue"]),
            "{{paper}}": palette.get("paper", DEFAULT_PALETTE["paper"])}
    os.makedirs(args.out, exist_ok=True)

    chrome = _find_chromium()
    if chrome:
        renderer = "headless chromium (%s)" % chrome
    else:
        renderer = None
    print("renderer: %s" % (renderer or
          "NONE -- falling back to Pillow parse/viewBox verification"))

    report = {"renderer": renderer or "none (parse check only)",
              "assets": []}
    failures = 0
    for entry in assets:
        asset_id = entry.get("id", "?")
        png_name = re.sub(r"[^A-Za-z0-9_-]+", "_", asset_id) + ".png"
        out_png = os.path.join(args.out, png_name)
        path = _resolve_file(entry, args.catalog)
        if not path:
            print("MISSING: %s (file %r not found)"
                  % (asset_id, entry.get("file")), file=sys.stderr)
            report["assets"].append({"id": asset_id, "status": "missing"})
            failures += 1
            continue
        with open(path) as f:
            svg_text = f.read()
        for ph, colour in subs.items():
            svg_text = svg_text.replace(ph, colour)
        vb = _viewbox(svg_text)
        if vb is None:
            print("BAD VIEWBOX: %s" % asset_id, file=sys.stderr)
            report["assets"].append({"id": asset_id,
                                     "status": "bad viewBox"})
            failures += 1
            continue
        if renderer is None:
            # No renderer: verify parse + viewBox only.
            report["assets"].append(
                {"id": asset_id, "status": "verified (no render)",
                 "viewBox": entry.get("viewBox")})
            print("verified (no render): %s" % asset_id)
            continue
        try:
            _render_chromium(chrome, svg_text, vb, out_png)
        except Exception as e:
            print("RENDER FAILED: %s: %s" % (asset_id, e),
                  file=sys.stderr)
            report["assets"].append({"id": asset_id, "status": "failed",
                                     "error": str(e)[:200]})
            failures += 1
            continue
        report["assets"].append({"id": asset_id, "status": "rendered",
                                 "png": png_name})
        print("rendered: %s -> %s" % (asset_id, png_name))
    with open(os.path.join(args.out, "preview-report.json"), "w") as f:
        json.dump(report, f, indent=2)
    if renderer is None:
        print("NOTE: no renderer was available, so no PNGs were made. "
              "Every SVG was verified to parse with a valid viewBox; "
              "visual QA still needs a renderer (resvg, cairosvg, or "
              "headless Chromium).")
    if failures:
        print("%d asset(s) failed" % failures, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
