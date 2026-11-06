#!/usr/bin/env python3
"""Normalise one SVG (or a directory of SVGs) into the pack format.

Reads a source SVG and writes a pack-ready normalised SVG:

  - REJECTS any file containing a raster image (<image>, data:image,
    or a raster href). The pack is code-drawn only; a raster file is
    an intake error, not something to fix up.
  - strips background <rect>s (a rect covering the whole viewBox in
    white/paper); the scene HTML supplies the #f6f1e7 paper.
  - maps every fill / stroke / stop-color / style colour through
    tools/palette-map.json (exact match first, hue fallback second)
    to the {{ink}} / {{red}} / {{blue}} placeholders (white ->
    "none"). The real palette is substituted at render time.
  - flattens linearGradient / radialGradient to a flat fill (the
    first stop's colour, palette-mapped); gradients cannot draw-on
    and do not survive the house style.
  - strips <filter>, <pattern>, and filter attributes.
  - sets stroke-linecap="round" and stroke-linejoin="round" on all
    stroked elements.
  - stroke-width: the house target is ~8% of the viewBox's smaller
    dimension (2 units on a 24 grid, the Tabler/Lucide ratio). A
    stroke-width already within 5-12% of the smaller dimension is
    left exactly as it is -- rescaling it would mangle icon stroke
    weights. A stroke-width outside that band is rescaled to the 8%
    target and the change is logged. A stroked element with no
    stroke-width gets the 8% target (otherwise it renders at the
    SVG default of 1 unit, hairline at scene scale). Every change
    is reported on stderr with --verbose; a per-file summary line
    is always printed.
  - prefixes every id and every url(#...) / href="#..." reference
    with the asset slug (--slug, default the filename stem) so ids
    cannot collide when several SVGs are inlined into one page.
    Already-prefixed ids are left alone, so the tool is idempotent.
  - removes comments, <metadata>, editor-namespace elements and
    empty groups; removes width/height from the root <svg> (the
    viewBox is the size authority). Keeps the viewBox exactly.

Idempotent: running it twice on its own output gives byte-identical
output (placeholders are not colours, ids are already prefixed,
stroke-widths are already in band, gradients/filters are gone).

Usage:
  normalize.py <input.svg> <output.svg> [--slug NAME]
  normalize.py --dir <in-dir> <out-dir> [--slug-prefix P]
Exit non-zero if any file is rejected (single-file mode) or if any
file in --dir mode fails; the other files are still processed.
"""
import argparse
import colorsys
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

RASTER_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")
TARGET_STROKE_RATIO = 0.08   # ~8% of the smaller viewBox dimension
STROKE_RATIO_LOW = 0.05
STROKE_RATIO_HIGH = 0.12
WHITE = {"#fff", "#ffffff", "#f6f1e7", "#fefefe", "#fafafa"}

# Numbers in path data / attribute values, for rounding.
_NUM_RE = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_HEX3_RE = re.compile(r"^#([0-9a-f])([0-9a-f])([0-9a-f])$")
_HEX6_RE = re.compile(r"^#[0-9a-f]{6}$")
_RGB_RE = re.compile(
    r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)"
    r"(?:\s*,\s*[\d.]+)?\s*\)$")
_URL_RE = re.compile(r"url\(#([^)]+)\)")
_STYLE_COLOUR_RE = re.compile(
    r"(fill|stroke|stop-color)\s*:\s*([^;!]+)")


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _norm_hex(value):
    """Normalise a colour token to lowercase #rrggbb, or None."""
    v = value.strip().lower()
    m = _HEX3_RE.match(v)
    if m:
        return "#" + "".join(c * 2 for c in m.groups())
    if _HEX6_RE.match(v):
        return v
    m = _RGB_RE.match(v)
    if m:
        return "#%02x%02x%02x" % tuple(int(x) for x in m.groups())
    return None


def _hue_classify(hexcol, fallback):
    """Hue fallback from palette-map.json: warm -> red, cool -> blue,
    neutral / near-white / near-black -> ink or transparent."""
    r = int(hexcol[1:3], 16) / 255.0
    g = int(hexcol[3:5], 16) / 255.0
    b = int(hexcol[5:7], 16) / 255.0
    h, li, s = colorsys.rgb_to_hls(r, g, b)
    hue = h * 360.0
    if li >= fallback.get("white_lightness", 0.97) and \
            s <= fallback.get("white_saturation", 0.1):
        return "none"
    if s <= fallback.get("neutral_saturation", 0.12):
        return "{{ink}}"
    if hue < fallback.get("warm_hue_below", 50) or \
            hue >= fallback.get("warm_hue_from", 330):
        return "{{red}}"
    return "{{blue}}"


class Palette:
    def __init__(self, path):
        with open(path) as f:
            data = json.load(f)
        self.exact = {k.strip().lower(): v
                      for k, v in data.get("exact", {}).items()}
        self.fallback = data.get("fallback", {})

    def map(self, value):
        """Map one colour token to a placeholder / 'none' / itself.

        Returns the mapped value. Tokens that are already placeholders,
        'none', 'transparent' or 'currentColor' pass through (currentColor
        is treated as ink, the pack's default stroke colour). Unparseable
        tokens (e.g. a var() or an unknown name) are left unchanged and
        reported by the caller.
        """
        v = value.strip()
        low = v.lower()
        if v.startswith("{{") or low in ("none", "transparent"):
            return v
        if low in self.exact:
            return self.exact[low]
        hexcol = _norm_hex(v)
        if hexcol is None:
            return None  # unparseable: caller keeps it and warns
        if hexcol in self.exact:
            return self.exact[hexcol]
        if hexcol in WHITE:
            return "none"
        return _hue_classify(hexcol, self.fallback)


def _iter_elements(root):
    for el in root.iter():
        yield el


def _reject_reasons(raw, root):
    """Raster / embedded-image checks. Returns a list of reasons."""
    reasons = []
    low = raw.lower()
    if "<image" in low:
        reasons.append("contains an <image> element (raster content)")
    if "data:image" in low:
        reasons.append("contains a data:image URI (embedded raster)")
    for el in _iter_elements(root):
        for attr in ("href", "{%s}href" % XLINK_NS):
            href = el.get(attr)
            if href and href.lower().split("?")[0].endswith(RASTER_EXTS):
                reasons.append(
                    "raster href %r on <%s>" % (href, _local(el.tag)))
    return reasons


def _parse_viewbox(root):
    vb = root.get("viewBox")
    if not vb:
        return None
    try:
        parts = [float(x) for x in vb.split()]
    except ValueError:
        return None
    if len(parts) != 4:
        return None
    return parts  # x, y, w, h


def _is_background_rect(el, vb):
    """True if this <rect> covers the whole viewBox in white/paper."""
    if _local(el.tag) != "rect":
        return False
    if vb is None:
        return False
    try:
        x = float(el.get("x", "0"))
        y = float(el.get("y", "0"))
        w = float(el.get("width", "0"))
        h = float(el.get("height", "0"))
    except ValueError:
        return False
    if not (x <= vb[0] and y <= vb[1] and
            x + w >= vb[0] + vb[2] and y + h >= vb[1] + vb[3]):
        return False
    fill = (el.get("fill") or "").strip().lower()
    if not fill:
        style = el.get("style") or ""
        m = re.search(r"fill\s*:\s*([^;]+)", style)
        fill = m.group(1).strip().lower() if m else ""
    hexcol = _norm_hex(fill) if fill else None
    return fill in ("", "white") or hexcol in WHITE


def _strip_empty_groups(root):
    """Remove <g> elements with no children and no meaningful attrs,
    bottom-up, until none remain."""
    changed = True
    while changed:
        changed = False
        for parent in list(root.iter()):
            for child in list(parent):
                if _local(child.tag) == "g" and len(child) == 0:
                    if not child.get("id"):
                        parent.remove(child)
                        changed = True


def normalize_file(src, dst, slug, palette, verbose=False):
    """Normalise one file. Returns (ok, [log lines]). Raises
    ValueError with the rejection reason for raster files."""
    with open(src, "rb") as f:
        raw_bytes = f.read()
    raw = raw_bytes.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError as e:
        raise ValueError("not parseable as XML: %s" % e)
    if _local(root.tag) != "svg":
        raise ValueError("root element is <%s>, not <svg>"
                         % _local(root.tag))
    reasons = _reject_reasons(raw, root)
    if reasons:
        raise ValueError("; ".join(reasons))

    log = []
    vb = _parse_viewbox(root)
    if vb is None:
        raise ValueError("missing or unparseable viewBox "
                         "(the viewBox is the size authority)")
    min_dim = min(vb[2], vb[3])
    target_sw = TARGET_STROKE_RATIO * min_dim

    # --- gradients: flatten to the first stop's mapped colour ------
    gradient_fill = {}
    for el in list(_iter_elements(root)):
        if _local(el.tag) in ("linearGradient", "radialGradient"):
            gid = el.get("id")
            first = None
            for stop in el.iter():
                if _local(stop.tag) == "stop":
                    first = stop.get("stop-color") or \
                        _style_colour(stop.get("style") or "",
                                      "stop-color")
                    break
            if gid and first:
                mapped = palette.map(first)
                gradient_fill[gid] = (mapped if mapped is not None
                                      else first)
            # the gradient element itself is removed below with defs
    # --- walk the tree: colours, strokes, filters, ids -------------
    unmapped = set()

    def map_colour(value):
        mapped = palette.map(value)
        if mapped is None:
            unmapped.add(value)
            return value
        return mapped

    def map_style(style):
        def repl(m):
            return "%s: %s" % (m.group(1), map_colour(m.group(2)))
        return _STYLE_COLOUR_RE.sub(repl, style)

    def visit(el, parent):
        tag = _local(el.tag)
        # drop editor cruft / metadata / filters / patterns outright
        if tag in ("metadata", "filter", "pattern") or \
                tag.startswith("sodipodi") or tag.startswith("inkscape"):
            if parent is not None:
                parent.remove(el)
            return
        # background rects go (the scene supplies the paper)
        if tag == "rect" and _is_background_rect(el, vb):
            if parent is not None:
                log.append("removed background rect")
                parent.remove(el)
            return
        # gradients are flattened, not kept
        if tag in ("linearGradient", "radialGradient"):
            if parent is not None:
                parent.remove(el)
            return
        # colour attributes
        for attr in ("fill", "stroke", "stop-color"):
            if el.get(attr) is not None:
                v = el.get(attr)
                if v.startswith("url(#"):
                    gid = v[5:-1]
                    if gid in gradient_fill:
                        el.set(attr, gradient_fill[gid])
                        log.append("flattened gradient #%s to %s"
                                   % (gid, gradient_fill[gid]))
                    else:
                        el.set(attr, "{{ink}}")
                        log.append("dropped unknown gradient #%s" % gid)
                else:
                    el.set(attr, map_colour(v))
        if el.get("style"):
            el.set("style", map_style(el.get("style")))
        # filter attributes go
        for attr in list(el.attrib):
            if attr == "filter" or attr.endswith("}filter"):
                del el.attrib[attr]
                log.append("stripped filter attribute")
        # stroked elements: round caps/joins, sane stroke-width
        stroke = el.get("stroke")
        if stroke is None and el.get("style"):
            stroke = _style_colour(el.get("style"), "stroke")
        if stroke and stroke != "none":
            if el.get("stroke-linecap") != "round":
                el.set("stroke-linecap", "round")
            if el.get("stroke-linejoin") != "round":
                el.set("stroke-linejoin", "round")
            sw = el.get("stroke-width")
            if sw is None:
                el.set("stroke-width", _fmt_num(target_sw))
                log.append("set missing stroke-width to %s "
                           "(8%% of %s viewBox)"
                           % (_fmt_num(target_sw), _fmt_num(min_dim)))
            else:
                try:
                    sw_f = float(sw)
                    ratio = sw_f / min_dim if min_dim else 0
                    if ratio < STROKE_RATIO_LOW or \
                            ratio > STROKE_RATIO_HIGH:
                        el.set("stroke-width", _fmt_num(target_sw))
                        log.append(
                            "rescaled stroke-width %s -> %s "
                            "(was %.1f%% of viewBox, target 8%%)"
                            % (sw, _fmt_num(target_sw), ratio * 100))
                except ValueError:
                    pass  # non-numeric stroke-width: leave alone
        # id prefixing (idempotent: already-prefixed ids are kept)
        eid = el.get("id")
        if eid and not eid.startswith(slug + "-"):
            el.set("id", slug + "-" + eid)
            log.append("prefixed id %s -> %s" % (eid, slug + "-" + eid))
        for child in list(el):
            visit(child, el)

    for child in list(root):
        visit(child, root)

    # url(#...) and href="#..." references follow the id prefixing.
    # Do this as a text pass over attribute values after the walk,
    # so references to ids renamed above are renamed the same way.
    for el in _iter_elements(root):
        for attr in list(el.attrib):
            v = el.attrib[attr]
            if "url(#" in v:
                def _url_repl(m):
                    ref = m.group(1)
                    if ref.startswith(slug + "-"):
                        return m.group(0)
                    return "url(#%s-%s)" % (slug, ref)
                el.attrib[attr] = _URL_RE.sub(_url_repl, v)
            if attr.endswith("href") and v.startswith("#"):
                ref = v[1:]
                if not ref.startswith(slug + "-"):
                    el.attrib[attr] = "#" + slug + "-" + ref

    # root <svg>: drop width/height (viewBox is the size authority),
    # keep the viewBox exactly.
    for attr in ("width", "height"):
        if root.get(attr) is not None:
            del root.attrib[attr]
    _strip_empty_groups(root)

    if unmapped:
        log.append("WARNING: unmapped colour tokens left as-is: %s"
                   % sorted(unmapped))
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    tree.write(dst, encoding="utf-8", xml_declaration=True)
    if verbose:
        for line in log:
            print("  %s: %s" % (os.path.basename(src), line),
                  file=sys.stderr)
    return log


def _style_colour(style, prop):
    m = re.search(re.escape(prop) + r"\s*:\s*([^;]+)", style or "")
    return m.group(1).strip() if m else None


def _fmt_num(x):
    s = "%.2f" % x
    return s.rstrip("0").rstrip(".") if "." in s else s


def _default_palette_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "palette-map.json")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", nargs="?", help="input SVG file")
    p.add_argument("output", nargs="?", help="output SVG file")
    p.add_argument("--dir", nargs=2, metavar=("IN_DIR", "OUT_DIR"),
                   help="normalise every .svg in IN_DIR into OUT_DIR")
    p.add_argument("--slug", default=None,
                   help="asset slug for id prefixing "
                        "(default: input filename stem)")
    p.add_argument("--palette-map", default=None,
                   help="palette-map.json path "
                        "(default: tools/palette-map.json)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    palette = Palette(args.palette_map or _default_palette_path())
    failures = 0

    if args.dir:
        in_dir, out_dir = args.dir
        files = sorted(f for f in os.listdir(in_dir)
                       if f.lower().endswith(".svg"))
        if not files:
            print("no .svg files in %s" % in_dir, file=sys.stderr)
            return 1
        for name in files:
            slug = args.slug or os.path.splitext(name)[0]
            src = os.path.join(in_dir, name)
            dst = os.path.join(out_dir, name)
            try:
                log = normalize_file(src, dst, slug, palette,
                                     verbose=args.verbose)
                print("ok: %s (%d normalisation notes)"
                      % (name, len(log)))
            except ValueError as e:
                failures += 1
                print("REJECTED %s: %s" % (name, e), file=sys.stderr)
        if failures:
            print("%d file(s) rejected" % failures, file=sys.stderr)
            return 1
        return 0

    if not args.input or not args.output:
        p.error("give <input.svg> <output.svg> or --dir <in> <out>")
    slug = args.slug or os.path.splitext(
        os.path.basename(args.input))[0]
    try:
        log = normalize_file(args.input, args.output, slug, palette,
                             verbose=args.verbose)
    except ValueError as e:
        print("REJECTED %s: %s" % (args.input, e), file=sys.stderr)
        return 1
    print("ok: %s -> %s (%d normalisation notes)"
          % (args.input, args.output, len(log)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
