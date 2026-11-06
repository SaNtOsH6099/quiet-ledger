#!/usr/bin/env python3
"""CSS check: does the beat's text actually fit inside the frame?

The guardrails' word-count limit is a proxy. This measures the real
rendered width of the text, from the CSS, and flags any line that
would run off the right edge (the failure that shipped in entry 3:
a 10-word hook line at 116px, clipped at the frame edge, which the
HyperFrames static check did not catch).

How it works:
- Reads the format's base template (base.html / base-longform.html)
  and parses its CSS for font-size and font-weight per class.
- Parses the beat's markup, finds every text-bearing element (HTML
  divs and SVG <text>), and for each one resolves its font-size and
  weight (inline style wins, else the class from the CSS).
- Measures the text width with PIL and DejaVu Sans (Bold for
  weight >= 700). DejaVu is a stand-in for Geist; it is close enough
  that a gross overflow is caught, and the check uses a 5% safety
  margin. If PIL or the font is unavailable, falls back to a
  character-width estimate (0.55em per char for bold, 0.5em for
  regular) so the check never crashes.
- For centred text (hook-line, close-line: text-align center, full
  width), overflow means the text is wider than the container.
  For left-positioned text, overflow means left + width passes the
  format's right margin.

Returns a list of problems, one per overflowing line. Empty means the
text fits.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails  # noqa: E402

# Fallback per-character width (fraction of the font size) when PIL or
# the font file is unavailable. Bold sans-serif is wider than regular.
CHAR_W_BOLD = 0.55
CHAR_W_REG = 0.50
# Safety margin: flag a line if it uses more than this fraction of the
# available width, so near-misses are caught too. Kept small (0.98):
# DejaVu is a stand-in for Geist, so a line that measures just under
# the frame in DejaVu could still clip in Geist. A tighter margin
# would reject legitimate short lines (a 2-word hook at 116px is
# already ~95% of a 1080px frame).
SAFETY = 0.98


def _font_path(bold):
    """DejaVu Sans (Bold), present on ubuntu-latest runners and most
    Linux. Returns None if the file is not there."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for base in ("/usr/share/fonts/truetype/dejavu",
                 "/usr/share/fonts"):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return None


def _measure(text, px, bold):
    """Width of text in pixels at font size px. Real measurement via
    PIL when possible, character-width estimate as fallback."""
    try:
        from PIL import ImageFont
        path = _font_path(bold)
        if path:
            font = ImageFont.truetype(path, int(px))
            return font.getlength(text)
    except Exception:
        pass
    w = CHAR_W_BOLD if bold else CHAR_W_REG
    return len(text) * w * px


def _css_classes(css):
    """Parse a stylesheet for font-size and font-weight per class.
    Returns {class_name: (font_size_px, font_weight)}."""
    out = {}
    for m in re.finditer(
            r"\.([a-zA-Z0-9_-]+)\s*\{([^}]*)\}", css):
        name, body = m.group(1), m.group(2)
        size = re.search(r"font-size:\s*([\d.]+)px", body)
        weight = re.search(r"font-weight:\s*(\d+)", body)
        if size:
            out[name] = (float(size.group(1)),
                         int(weight.group(1)) if weight else 400)
    return out


def _inline_style(style):
    """Parse an inline style attribute into a dict."""
    out = {}
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _px(value, default=None):
    """Parse a '123px' value; returns default if it is not a px value."""
    if value is None:
        return default
    m = re.match(r"([\d.]+)px$", value)
    return float(m.group(1)) if m else default


def check_markup(markup, fmt="shorts"):
    """Check one beat's markup for text that would overflow the frame.
    Returns a list of problem strings (empty = fits)."""
    g = guardrails.get(fmt)
    canvas_w = g["canvas"][0]
    right_edge = g["margins"]["right"]
    # The base template's CSS is the source of truth for font sizes.
    templates_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "templates")
    base_path = os.path.join(templates_dir, g["base_template"])
    try:
        css = open(base_path).read()
    except OSError:
        css = ""
    classes = _css_classes(css)
    problems = []

    # --- HTML text divs -----------------------------------------------
    for m in re.finditer(
            r'<div class="([^"]+)"([^>]*)>(.*?)</div>',
            markup, re.DOTALL):
        cls_list = m.group(1).split()
        attrs = m.group(2)
        inner = m.group(3)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        style_m = re.search(r'style="([^"]*)"', attrs)
        style = _inline_style(style_m.group(1)) if style_m else {}
        # font size: inline style wins, else the first class in the CSS
        size = _px(style.get("font-size"))
        weight = 400
        if size is None:
            for c in cls_list:
                if c in classes:
                    size, weight = classes[c]
                    break
        if size is None:
            size = 34
        # bold if the weight is 700+ or the inline style says bold
        fw = style.get("font-weight")
        if fw and fw.isdigit():
            weight = int(fw)
        bold = weight >= 700
        width = _measure(text, size, bold)
        # centred full-width lines (hook-line, close-line) overflow
        # when the text is wider than the container itself
        centred = ("hook-line" in cls_list or "close-line" in cls_list)
        if centred:
            if width > canvas_w * SAFETY:
                problems.append(
                    f"text overflows the frame: {text[:40]!r} is "
                    f"about {int(width)}px wide at {int(size)}px in a "
                    f"{canvas_w}px frame")
            continue
        # left-positioned text overflows when left + width passes the
        # right margin
        left = _px(style.get("left"), 0) or 0
        if left + width > right_edge * SAFETY:
            problems.append(
                f"text overflows the right edge: {text[:40]!r} starts "
                f"at {int(left)}px and is about {int(width)}px wide "
                f"(right margin {right_edge}px)")

    # --- SVG <text> elements -----------------------------------------
    for m in re.finditer(
            r'<text([^>]*)>(.*?)</text>', markup, re.DOTALL):
        attrs, inner = m.group(1), m.group(2)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        cls_m = re.search(r'class="([^"]+)"', attrs)
        size = None
        weight = 400
        if cls_m:
            for c in cls_m.group(1).split():
                if c in classes:
                    size, weight = classes[c]
                    break
        if size is None:
            size = 34
        # SVG text has no font-size attr here; fall back to the class
        # size (already resolved) or 34px.
        bold = weight >= 700
        width = _measure(text, size, bold)
        x_m = re.search(r'\bx="([\d.]+)"', attrs)
        x = float(x_m.group(1)) if x_m else 0
        anchor_m = re.search(r'text-anchor="([^"]+)"', attrs)
        anchor = anchor_m.group(1) if anchor_m else "start"
        if anchor == "middle":
            # centred on x: overflow if either side passes the edge
            if x - width / 2 < 0 or x + width / 2 > right_edge * SAFETY:
                problems.append(
                    f"SVG text overflows: {text[:40]!r} is about "
                    f"{int(width)}px wide, centred at x={int(x)}")
        elif x + width > right_edge * SAFETY:
            problems.append(
                f"SVG text overflows the right edge: {text[:40]!r} "
                f"starts at x={int(x)} and is about {int(width)}px wide")
    return problems
