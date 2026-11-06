#!/usr/bin/env python3
"""Inline catalog assets into beat markup.

Reference syntax (written by Muse in a beat's markup):

    <g data-asset="<catalog id>" data-x="<cx>" data-y="<cy>"
       data-w="<width>"></g>

  - <catalog id> is an id from assets/catalog.json, in
    "library:slug" form, e.g. "wikimedia:eiffel-tower" or
    "tabler:chart-line". A self-closing form
    <g data-asset="..." data-x="..." data-y="..." data-w="..." />
    is also accepted.
  - (cx, cy) is the centre point of the placed asset, in canvas
    coordinates (1080x1920 for Shorts).
  - w is the target width in px. The height follows from the asset's
    viewBox aspect ratio: scale = w / viewBox_width,
    height = viewBox_height * scale.

For each reference resolve_assets() looks the id up in the catalog
(raising ValueError with the id when it is not found -- fail loudly,
never silently drop an object), loads the normalised SVG, substitutes
the {{ink}} / {{red}} / {{blue}} placeholders with the palette
(default ink #1c1c1c, red #d9481f, blue #2b5ea7), and wraps the inner
content as:

    <g transform="translate(cx - w/2, cy - h/2) scale(s)">...</g>

Where the SVG comes from: the pack lives on Drive, not in the repo.
The catalog's "file" is the path relative to the Drive `assets/`
folder (e.g. "landmarks/eiffel-tower.svg"). resolve first tries the
local file (repo checkout, or Muse's local pack copy, for testing);
when it is not there, it fetches the file from Drive
(pipeline.assets.drive_fetch: finds the `assets` folder under the
Drive root, navigates the category subfolders by path, downloads the
file bytes; OAuth as the user, the same credentials the ingest and
upload jobs use). The scenes job installs the Drive tools and passes
the Drive secrets, so the fetch works at render time. A missing
asset raises, so a render never silently ships without it.

Inner ids are already prefixed by normalize.py, but a safety
re-prefix is applied here too: any id that does not already carry
the asset slug (or the source file's stem) gets the asset slug
prepended, so a file that slipped through unprefixed cannot collide
with another asset's ids once inlined.

Markup with no asset references is returned unchanged. Stdlib only,
except the Drive fetch, which is lazily imported and only runs when
a referenced asset is not on local disk.
"""
import os
import re

from pipeline.assets import catalog as catalog_mod

# <g data-asset="..." ...></g> or self-closing <g data-asset="..." ... />
_REF_RE = re.compile(
    r'<g\s+[^>]*data-asset="([^"]+)"[^>]*(?:/>|>\s*</g>)')
_ATTR_RE = re.compile(r'data-(x|y|w)="([^"]+)"')
_ID_RE = re.compile(r'\bid="([^"]+)"')
_URL_RE = re.compile(r"url\(#([^)]+)\)")
_HREF_RE = re.compile(r'href="#([^"]+)"')


def _fmt_num(x):
    s = "%.2f" % x
    return s.rstrip("0").rstrip(".") if "." in s else s


def _slug(asset_id):
    return asset_id.replace(".", "-").replace("_", "-")


def _reprefix(inner, asset_id, file_stem):
    """Safety re-prefix of inner ids with the asset slug. Ids that
    already carry the asset slug or the file stem are left alone;
    bare ids get the slug. References (url(#...), href="#...") are
    renamed to match."""
    slug = _slug(asset_id)
    renames = {}

    def _id_repl(m):
        old = m.group(1)
        if old.startswith(slug + "-") or \
                (file_stem and old.startswith(file_stem + "-")):
            return m.group(0)
        new = slug + "-" + old
        renames[old] = new
        return 'id="%s"' % new

    out = _ID_RE.sub(_id_repl, inner)
    if renames:
        def _url_repl(m):
            return "url(#%s)" % renames.get(m.group(1), m.group(1))
        out = _URL_RE.sub(_url_repl, out)

        def _href_repl(m):
            return 'href="#%s"' % renames.get(m.group(1), m.group(1))
        out = _HREF_RE.sub(_href_repl, out)
    return out


def _inner_content(svg_text):
    """Return (inner XML, viewBox (x, y, w, h)) for a normalised SVG.

    String extraction, not an XML round-trip: re-serialising with
    ElementTree would inject ns0: prefixes on namespaced elements,
    which do not render when inlined into HTML. The inner markup is
    kept byte-for-byte as normalize.py wrote it.
    """
    svg_start = svg_text.find("<svg")
    if svg_start == -1:
        raise ValueError("asset SVG has no <svg> root element")
    open_end = svg_text.find(">", svg_start)
    close_start = svg_text.rfind("</svg>")
    if open_end == -1 or close_start == -1 or close_start <= open_end:
        raise ValueError("asset SVG is not a well-formed <svg>...</svg>")
    root_tag = svg_text[svg_start:open_end + 1]
    m = re.search(r'viewBox="([^"]+)"', root_tag)
    if not m:
        raise ValueError("asset SVG has no viewBox")
    try:
        parts = [float(x) for x in m.group(1).split()]
    except ValueError:
        raise ValueError("asset SVG viewBox %r does not parse"
                         % m.group(1))
    if len(parts) != 4:
        raise ValueError("asset SVG viewBox %r is not four numbers"
                         % m.group(1))
    return svg_text[open_end + 1:close_start], parts


def resolve_assets(markup, palette=None):
    """Replace every <g data-asset="..."> reference in markup with
    the inlined, palette-substituted SVG content. Raises ValueError
    for an unknown asset id, a missing catalog, a missing asset file
    (neither on local disk nor on Drive), or a reference without
    data-x / data-y / data-w."""
    if "data-asset" not in markup:
        return markup
    pal = dict(catalog_mod.DEFAULT_PALETTE)
    if palette:
        pal.update(palette)
    by_id = catalog_mod.assets_by_id()
    if not catalog_mod.load_catalog():
        raise ValueError(
            "markup references assets but assets/catalog.json "
            "was not found; cannot resolve asset references")

    def _replace(m):
        asset_id = m.group(1)
        attrs = dict(_ATTR_RE.findall(m.group(0)))
        for key in ("x", "y", "w"):
            if key not in attrs:
                raise ValueError(
                    "asset reference %r is missing data-%s "
                    "(need data-x, data-y and data-w)"
                    % (asset_id, key))
        try:
            cx, cy, w = (float(attrs["x"]), float(attrs["y"]),
                         float(attrs["w"]))
        except ValueError:
            raise ValueError(
                "asset reference %r has a non-numeric data-x / "
                "data-y / data-w" % asset_id)
        entry = by_id.get(asset_id)
        if entry is None:
            raise ValueError(
                "asset id %r not found in catalog" % asset_id)
        # Local file first (repo checkout or Muse's local pack copy,
        # for testing); otherwise fetch from Drive, where the pack
        # lives. The catalog "file" is the Drive-relative path.
        path = catalog_mod.asset_file_path(entry)
        if path is not None:
            with open(path) as f:
                svg_text = f.read()
        else:
            from pipeline.assets import drive_fetch  # noqa: PLC0415
            svg_text = drive_fetch.fetch_asset_text(
                entry.get("file", ""))
        inner, vb = _inner_content(svg_text)
        for ph, colour in (("{{ink}}", pal["ink"]),
                           ("{{red}}", pal["red"]),
                           ("{{blue}}", pal["blue"]),
                           ("{{paper}}", pal["paper"])):
            inner = inner.replace(ph, colour)
        # re-prefix against the (substituted) inner content
        file_stem = os.path.splitext(
            os.path.basename(entry.get("file", "")))[0]
        inner = _reprefix(inner, asset_id, file_stem)
        scale = w / vb[2] if vb[2] else 0
        h = vb[3] * scale
        tx, ty = cx - w / 2.0, cy - h / 2.0
        return ('<g transform="translate(%s, %s) scale(%s)">%s</g>'
                % (_fmt_num(tx), _fmt_num(ty), _fmt_num(scale), inner))

    return _REF_RE.sub(_replace, markup)
