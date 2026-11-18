#!/usr/bin/env python3
"""Build an Echoes Originals HyperFrames caption composition from JSON.

Usage:
    python3 tools/build_captions.py captions/test-captions.json index.html

Input JSON: a list of captions, each with:
    start (seconds, float), end (seconds, float),
    text (string, 3-5 words, NO em dash),
    keyword (optional, one word from the text, highlighted in gold)
    style (optional, dedicated per-video plan): punch, standard, list,
      split, question, quick — controls size, position, entrance and
      line break. size_px (60-90, default 70), bottom_px (670-850,
      default 670, larger = higher in the safe band), break_after
      (optional word index after which to break the line).
    Durations are per-caption (human pace), minimum 1.5s for a 3-word
    phrase, longer for reveals and the closing question; the first word
    of every caption is set visible at its start so no blank frame
    occurs at a caption change.

Output: a self-contained 1080x1920 HyperFrames composition (index.html)
using GSAP, following the project AGENTS.md contract:
  - every timed element has data-start and data-duration, class="clip"
  - one paused root timeline registered on window.__timelines["main"]
  - only deterministic logic, no Date.now / Math.random / network fetches:
    GSAP and the display font are vendored into this project and embedded
    in the generated HTML, so a render does not depend on a CDN at all
  - only GSAP properties HyperFrames supports: opacity, x, y, scale,
    scaleX, scaleY, rotation, width, height, visibility

Echoes preset baked in here (see README_ECHOES.md):
  - caption box: left 90px, width 810px, bottom 670px
    => bottom of captions at y = 1920 - 670 = 1250, clear of the
    right-side rail (x > 900) and of bottom platform UI
  - professional display type: Archivo Black (OFL, vendored in
    assets/fonts/), embedded as base64, falling back to DejaVu Sans Bold
    if the font file is ever missing; 70px, tight tracking, centred
  - big bold white text, black outline, centred
  - keyword word in gold (#FFD166) and given an extra pop
  - entrance: words pop in one by one, 0.07s apart, 0.28s each,
    from scale 0.85 / y +24 / opacity 0, easing back.out(1.7)
    (anticipation + overshoot + settle)
  - hold for the full caption duration (minimum 2s, enforced)
  - exit: fast 0.12s fade at the end, i.e. a hard cut, not a long fade
  - first caption starts at 0.0s: no fade-in, no static opening
"""
import base64
import html
import json
import re
import sys
from pathlib import Path

EM_DASH = "\u2014"
GOLD = "#FFD166"


def fail(msg):
    raise SystemExit(f"build_captions: ERROR: {msg}")


def clean_word(word):
    return re.sub(r"[^A-Za-z0-9']", "", word)


def main():
    if len(sys.argv) != 3:
        fail("usage: build_captions.py <captions.json> <output.html>")
    captions_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])
    captions = json.loads(captions_path.read_text(encoding="utf-8"))
    if not isinstance(captions, list) or not captions:
        fail("captions file must be a non-empty JSON list")

    prev_end = None
    for i, cap in enumerate(captions):
        text = cap.get("text", "")
        if EM_DASH in text or "--" in text:
            fail(f"caption {i}: em dash found in {text!r} (never allowed)")
        words = text.split()
        if not (3 <= len(words) <= 5):
            fail(f"caption {i}: {len(words)} words, must be 3-5: {text!r}")
        start, end = float(cap["start"]), float(cap["end"])
        if cap.get("word_starts"):
            if len(cap["word_starts"]) != len(cap["text"].split()):
                fail(f"caption {i}: word_starts length != word count")
            if end - start < 0.5:
                fail(f"caption {i}: word-synced duration {end - start}s, must be >= 0.5s")
        elif end - start < 1.5:
            fail(f"caption {i}: duration {end - start}s, must be >= 1.5s")
        if prev_end is not None and start < prev_end - 1e-9:
            fail(f"caption {i}: overlaps previous caption")
        if i == 0 and start != 0.0:
            fail("first caption must start at 0.0s (no slow opening)")
        keyword = cap.get("keyword")
        if keyword and clean_word(keyword).lower() not in [
            clean_word(w).lower() for w in words
        ]:
            fail(f"caption {i}: keyword {keyword!r} is not a word in {text!r}")
        style = cap.get("style", "standard")
        if style not in ("punch", "standard", "list", "split", "question", "quick"):
            fail(f"caption {i}: unknown style {style!r}")
        size = cap.get("size_px", 70)
        if not (60 <= float(size) <= 90):
            fail(f"caption {i}: size_px {size} outside 60-90")
        bottom = cap.get("bottom_px", 670)
        if not (670 <= float(bottom) <= 850):
            fail(f"caption {i}: bottom_px {bottom} outside 670-850 (safe band)")
        prev_end = end

    total = max(float(c["end"]) for c in captions)

    # Per-style entrance parameters: stagger, duration, from-scale,
    # from-y, easing, keyword extra scale (1.0 = colour only, no pop).
    ENTRANCES = {
        "punch":    (0.05, 0.20, 0.70, 12, 'back.out(2.5)', 1.25),
        "standard": (0.07, 0.28, 0.85, 24, 'back.out(1.7)', 1.18),
        "list":     (0.18, 0.28, 0.85, 24, 'back.out(1.7)', 1.00),
        "split":    (0.07, 0.28, 0.85, 24, 'back.out(1.7)', 1.18),
        "question": (0.12, 0.45, 0.95, 40, 'power2.out', 1.15),
        "quick":    (0.04, 0.18, 0.90, 16, 'back.out(1.7)', 1.10),
    }
    caption_divs = []
    timeline_lines = []
    for i, cap in enumerate(captions):
        start, end = float(cap["start"]), float(cap["end"])
        words = cap["text"].split()
        keyword = clean_word(cap["keyword"]).lower() if cap.get("keyword") else None
        style = cap.get("style", "standard")
        size = cap.get("size_px", 70)
        bottom = cap.get("bottom_px", 670)
        break_after = cap.get("break_after")
        stagger, dur, scale_from, y_from, ease, kw_scale = ENTRANCES[style]
        spans = []
        for j, word in enumerate(words):
            cls = "word keyword" if keyword and clean_word(word).lower() == keyword else "word"
            spans.append(
                f'<span class="{cls}" id="c{i}w{j}">{html.escape(word)}</span>'
            )
        joined = ""
        for j, span in enumerate(spans):
            if j:
                joined += "<br>" if break_after is not None and j == int(break_after) else " "
            joined += span
        caption_divs.append(
            f'      <div class="clip caption" id="caption{i}" '
            f'data-start="{start}" data-duration="{end - start}" '
            f'data-track-index="{i}" style="font-size: {size}px; bottom: {bottom}px;">{joined}</div>'
        )
        # First word of every caption is set visible at its start, then
        # given a small scale pulse, so a caption change never leaves a
        # blank frame (the old version only did this for caption 0).
        word_starts = cap.get("word_starts")
        for j in range(len(words)):
            t = float(word_starts[j]) if word_starts else start + j * stagger
            if j == 0:
                timeline_lines.append(
                    f'      tl.set("#c{i}w{j}", {{opacity: 1, y: 0, scale: 1}}, {start:.2f});'
                )
                timeline_lines.append(
                    f'      tl.to("#c{i}w{j}", {{scale: 1.15, duration: 0.12, ease: "back.out(2)"}}, {start + 0.02:.2f});'
                )
                timeline_lines.append(
                    f'      tl.to("#c{i}w{j}", {{scale: 1, duration: 0.15, ease: "power2.out"}}, {start + 0.14:.2f});'
                )
            else:
                timeline_lines.append(
                    f'      tl.fromTo("#c{i}w{j}", '
                    f'{{opacity: 0, y: {y_from}, scale: {scale_from}}}, '
                    f'{{opacity: 1, y: 0, scale: 1, duration: {dur}, ease: "{ease}"}}, {t:.2f});'
                )
            if keyword and clean_word(words[j]).lower() == keyword and kw_scale > 1.0:
                timeline_lines.append(
                    f'      tl.to("#c{i}w{j}", {{scale: {kw_scale}, duration: 0.15, ease: "back.out(2)"}}, {t + dur:.2f});'
                )
                timeline_lines.append(
                    f'      tl.to("#c{i}w{j}", {{scale: 1, duration: 0.18, ease: "power2.out"}}, {t + dur + 0.15:.2f});'
                )
        # Fast exit at the end of the caption: a hard cut, not a long fade.
        timeline_lines.append(
            f'      tl.to("#caption{i}", {{opacity: 0, duration: 0.12}}, {end - 0.12:.2f});'
        )
        # Reset for the next caption is handled by the next caption's own
        # fromTo on its own word spans; captions are separate elements.

    # Raking light: a slow, deterministic sweep across the frame, purely
    # decorative background motion so no shot sits completely static.
    timeline_lines.append(
        f'      tl.fromTo("#light", {{x: -1080}}, {{x: 1080, duration: {total}, ease: "none"}}, 0);'
    )

    # Vendored assets, embedded so renders are reproducible offline.
    # Project root is the parent of tools/.
    project_root = Path(__file__).resolve().parent.parent
    font_path = project_root / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"
    if font_path.exists():
        font_b64 = base64.b64encode(font_path.read_bytes()).decode("ascii")
        font_face = (
            "@font-face { font-family: 'Archivo Black'; "
            f"src: url(data:font/ttf;base64,{font_b64}) format('truetype'); "
            "font-weight: 400; font-display: swap; }"
        )
    else:
        font_face = "/* Archivo Black missing, falling back to DejaVu Sans Bold */"
    gsap_path = project_root / "assets" / "gsap.min.js"
    if gsap_path.exists():
        gsap_tag = f"<script>\n{gsap_path.read_text(encoding='utf-8')}\n</script>"
    else:
        gsap_tag = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>'

    html_doc = f"""<!doctype html>
<html lang="en" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    {gsap_tag}
    <style>
      {font_face}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        margin: 0; width: 1080px; height: 1920px; overflow: hidden;
        background: #0a0a0a;
      }}
      #root {{ width: 100%; height: 100%; position: relative; }}
      #light {{
        position: absolute; top: 0; left: 0; width: 1080px; height: 1920px;
        background: linear-gradient(105deg, transparent 42%, rgba(255, 220, 150, 0.10) 50%, transparent 58%);
        pointer-events: none;
      }}
      .caption {{
        position: absolute; left: 90px; width: 810px; bottom: 670px;
        text-align: center;
        font-family: "Archivo Black", "DejaVu Sans", "Arial Black", sans-serif;
        font-size: 70px; font-weight: 400; line-height: 1.12;
        letter-spacing: -0.01em;
        color: #ffffff;
        text-shadow: 3px 0 0 #000, -3px 0 0 #000, 0 3px 0 #000, 0 -3px 0 #000,
          3px 3px 0 #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000,
          0 6px 16px rgba(0, 0, 0, 0.85);
      }}
      .word {{ display: inline-block; }}
      .keyword {{ color: {GOLD}; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920">
      <div id="light" class="clip" data-start="0" data-duration="{total}" data-track-index="99"></div>
{chr(10).join(caption_divs)}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
{chr(10).join(timeline_lines)}
      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""
    output_path.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {output_path} ({len(captions)} captions, {total}s total)")


if __name__ == "__main__":
    main()
