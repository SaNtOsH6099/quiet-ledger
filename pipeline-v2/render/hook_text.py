#!/usr/bin/env python3
"""Inject a Director-plan hook text overlay into a generated Hormozi
caption HTML (text or plate variant), mirroring the date-card pattern
exactly.

A hook text is the approved on-screen text on the opening shot
(Director plan §6): a second fact, not duplicating the spoken line,
in the lower-third safe zone for the full shot. The captions.json
schema has NO hook-text entry type, and the v2 render consumes caption
VIDEOS (text + plate mp4s), so the hook text lives in the HyperFrames
HTML, in BOTH variants:
  - text variant: gold #FFD166 text (the 57 thumbnail text family),
    same heavy black stroke + drop shadow as the captions, no plate
    (the plate lives in the other layer).
  - plate variant: text transparent, dark plate bar behind the text
    (same rgba(0,0,0,0.72) + border-radius + box-shadow spread as the
    word plates), so the multiply blend darkens the footage there.

Input file (hook_text.json, staged per video, optional):
  {"text": "NO ONE EVER CAME FORWARD", "start": 0.0, "end": 8.7}
"text" and "start" are required; "end" defaults to start + 8.7 only
when omitted is NOT allowed — the window is the shot, so "end" (or
"duration" as an alias) is required. Optional "size_px" (default 72)
and "bottom_px" (default 550 — bottom edge 550px above the frame
bottom, i.e. y 1370 in a 1920-high frame, 71% down: the lower-third
safe zone, below the captions at bottom 1000 and clear of the bottom
platform UI).

Structure mirrors the generated captions and the date cards:
  - div: class "clip hooktext", data-start / data-duration /
    data-track-index (200, a display lane only), inline font-size
    72px + bottom 550px, plain text (no word spans — the whole text
    fades as one unit, and it stays on screen for the full shot).
  - CSS: a .hooktext rule added to the <style> block
    (variant-dependent plate/text treatment), positioned like
    .caption (left 50px, width 980px, flex column, centred) but at
    bottom: 550px.
  - GSAP: fade-in fromTo (opacity 0 -> 1, 0.12s) at the start
    and fade-out to (opacity 0, 0.12s) at end - 0.12, mirroring the
    caption group fade-outs and the date cards. fromTo immediateRender
    holds the text invisible until its fade-in, exactly as the caption
    words are held.

Provenance: generalised from pipeline-v2/render/date_cards.py (the
69-proven injector), which is itself the Gate-3-proven local injector.
The one real bug that injector caught — inserting after the FIRST
</div> following a caption div nests the overlay INSIDE the last
caption (because caption divs contain nested <div class="line">
elements) — is preserved here as a depth-counted insertion plus a
verification assert (no caption div may open after the hook-text div).
`npm run check`'s nested_clip_never_visible warning is the catch for
it; the assert here fails the build before the render runs.

Why this exists (63 Gate 4 FAIL, 2026-11-20): the approved hook text
"NO ONE EVER CAME FORWARD" (Gate 0 verdict, Director plan §6, Gate 3
report §5) shipped as two layers — the text lived only in plan/report
prose, with no renderable input, so no S1 frame showed it and no gate
verified it on screen. The fix is this input + injector, the same
class as the date cards. Gate 3 must verify every planned on-screen
text element exists in a BUILD INPUT, not just in report prose.

Usage as a module (echoes_captions_v2.py calls inject()):
  from hook_text import load, inject
  hook = load("in/hook_text.json")
  html = inject(html_text, hook)

Usage standalone (debugging a generated HTML):
  python3 hook_text.py <hook_text.json> <input.html> <output.html>
"""
import json
import sys

FADE = 0.12
SIZE_PX = 72
BOTTOM_PX = 550
TRACK_INDEX = 200
GOLD = "#FFD166"

SHADOW = (
    "6px 0 0 #000, -6px 0 0 #000, 0 6px 0 #000, 0 -6px 0 #000,\n"
    "          6px 6px 0 #000, -6px -6px 0 #000, 6px -6px 0 #000, -6px 6px 0 #000,\n"
    "          0 10px 24px rgba(0, 0, 0, 0.95)"
)
PLATE = (
    "background: rgba(0, 0, 0, 0.72);\n"
    "        border-radius: 0.14em;\n"
    "        box-shadow: 0 0 0 0.10em rgba(0, 0, 0, 0.72);"
)


def load(path):
    """Read a hook_text.json file into (text, start, end, size_px,
    bottom_px).

    Validates: a JSON object with text + start + end (or duration);
    text non-empty ALL-CAPS, no em dash, at most 7 words (Director
    plan §6: hook text is at most 7 words); start >= 0; end > start
    with duration >= 0.5s; size_px in 48-110; bottom_px in 300-900
    (below the captions at bottom 950-1050, clear of the bottom
    platform UI).
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("hook_text.json must be a JSON object, not a list")
    text = raw.get("text", "")
    if not text or text != text.upper():
        raise ValueError(f"hook text must be non-empty ALL-CAPS: {text!r}")
    if "\u2014" in text or "--" in text:
        raise ValueError(f"hook text must not contain an em dash: {text!r}")
    words = text.split()
    if len(words) > 7:
        raise ValueError(
            f"hook text is {len(words)} words, must be at most 7: {text!r}")
    if "start" not in raw:
        raise ValueError("hook_text.json: missing 'start'")
    start = float(raw["start"])
    if start < 0:
        raise ValueError(f"hook_text.json: negative start {start}")
    if "end" in raw:
        end = float(raw["end"])
    elif "duration" in raw:
        end = start + float(raw["duration"])
    else:
        raise ValueError(
            "hook_text.json: missing 'end' (or 'duration') — the window "
            "is the shot, it must be stated")
    if end - start < 0.5:
        raise ValueError(
            f"hook text duration {end - start:.2f}s, must be >= 0.5s")
    size_px = float(raw.get("size_px", SIZE_PX))
    if not 48 <= size_px <= 110:
        raise ValueError(f"hook text size_px {size_px} outside 48-110")
    bottom_px = float(raw.get("bottom_px", BOTTOM_PX))
    if not 300 <= bottom_px <= 900:
        raise ValueError(
            f"hook text bottom_px {bottom_px} outside 300-900 "
            "(below the captions at bottom 950-1050, clear of the "
            "bottom platform UI)")
    return (text, start, end, size_px, bottom_px)


def inject(html, hook):
    """Return html with the hook text injected. Refuses to run twice."""
    if "hooktext" in html:
        raise ValueError("HTML already has a hook text — refusing to inject twice")
    text, start, end, size_px, bottom_px = hook
    n_caps = html.count('class="clip caption"')
    if n_caps < 1:
        raise ValueError("no caption divs found — is this a generated caption HTML?")

    plate_only = "background: #ffffff;" in html
    if not (plate_only or "background: #0a0a0a;" in html):
        raise ValueError("cannot detect variant from page background")

    # 1. CSS rule, after the .yl rule (last rule in the <style> block).
    if plate_only:
        hook_css = (
            "      .hooktext {\n"
            "        position: absolute; left: 50px; width: 980px;\n"
            "        display: flex; flex-direction: column; align-items: center;\n"
            "        text-align: center;\n"
            "        font-family: \"Anton\", \"DejaVu Sans\", \"Arial Black\", sans-serif;\n"
            "        font-size: 72px; font-weight: 400; line-height: 1.05;\n"
            "        letter-spacing: 0.01em;\n"
            "        color: transparent;\n"
            "        text-shadow: none;\n"
            f"        {PLATE}\n"
            "      }\n"
        )
    else:
        hook_css = (
            "      .hooktext {\n"
            "        position: absolute; left: 50px; width: 980px;\n"
            "        display: flex; flex-direction: column; align-items: center;\n"
            "        text-align: center;\n"
            "        font-family: \"Anton\", \"DejaVu Sans\", \"Arial Black\", sans-serif;\n"
            "        font-size: 72px; font-weight: 400; line-height: 1.05;\n"
            "        letter-spacing: 0.01em;\n"
            f"        color: {GOLD};\n"
            f"        text-shadow: {SHADOW};\n"
            "      }\n"
        )
    anchor = '      .yl { display: inline-block; position: absolute; left: 0; top: 0; color: '
    idx = html.index(anchor)
    line_end = html.index("\n", idx) + 1
    html = html[:line_end] + hook_css + html[line_end:]

    # 2. Hook-text div, after the last caption div inside #root.
    # The caption divs contain nested <div class="line"> elements, so
    # the first </div> after a caption div's start closes a LINE, not
    # the caption div — inserting there nests the overlay inside the
    # last caption (caught by `npm run check`: nested_clip_never_visible,
    # the text would never appear). Count div depth from the last
    # caption div's opening tag until it returns to zero.
    last_cap = html.rindex('class="clip caption"')
    open_tag = html.rindex("<div", 0, last_cap)
    depth = 0
    i = open_tag
    div_end = None
    while i < len(html):
        if html.startswith("<div", i):
            depth += 1
            i += 4
        elif html.startswith("</div>", i):
            depth -= 1
            i += len("</div>")
            if depth == 0:
                div_end = i
                break
        else:
            i += 1
    if div_end is None:
        raise ValueError("could not find the end of the last caption div")
    dur = round(end - start, 2)
    # The inline size/bottom override the CSS defaults when the staged
    # file states them; the CSS carries the defaults.
    size_str = f"{size_px:g}"
    bottom_str = f"{bottom_px:g}"
    div = (
        f'      <div class="clip hooktext" id="hooktext" '
        f'data-start="{start}" data-duration="{dur}" '
        f'data-track-index="{TRACK_INDEX}" '
        f'style="font-size: {size_str}px; bottom: {bottom_str}px;">{text}</div>'
    )
    html = html[:div_end] + "\n" + div + html[div_end:]

    # 3. GSAP tweens, before the window.__timelines registration.
    tweens = [
        f'      tl.fromTo("#hooktext", {{opacity: 0}}, '
        f'{{opacity: 1, duration: {FADE}, ease: "power2.out"}}, {start:.2f});',
        f'      tl.to("#hooktext", {{opacity: 0, duration: {FADE}}}, '
        f'{end - FADE:.2f});',
    ]
    marker = '      window.__timelines = window.__timelines || {};'
    idx = html.index(marker)
    html = html[:idx] + "\n".join(tweens) + "\n" + html[idx:]

    # 4. Verify the injection.
    if html.count('class="clip hooktext"') != 1:
        raise ValueError("expected exactly 1 hook-text div")
    # The hook text must be a sibling of the caption divs inside #root,
    # NOT nested inside the last caption div (the nested_clip_never_visible
    # bug): no caption div may open after the hook-text div.
    first_hook = html.index('class="clip hooktext"')
    if 'class="clip caption"' in html[first_hook:]:
        raise ValueError("hook text is nested inside a caption div — insertion point wrong")
    if 'id="hooktext" data-start="' not in html:
        raise ValueError("hook-text div missing")
    if 'tl.fromTo("#hooktext"' not in html:
        raise ValueError("hook-text fade-in missing")
    if 'tl.to("#hooktext"' not in html:
        raise ValueError("hook-text fade-out missing")
    if text not in html:
        raise ValueError("hook text missing")
    return html


def main(argv):
    hook_path, inp, outp = argv[1], argv[2], argv[3]
    hook = load(hook_path)
    with open(inp, encoding="utf-8") as f:
        html = f.read()
    html = inject(html, hook)
    with open(outp, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {outp} (hook text injected: {hook[0]!r} "
          f"{hook[1]:.2f}-{hook[2]:.2f}s)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: hook_text.py <hook_text.json> <input.html> <output.html>")
    raise SystemExit(main(sys.argv))
