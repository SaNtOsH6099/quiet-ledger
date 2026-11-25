#!/usr/bin/env python3
"""Build an Echoes Originals HyperFrames caption composition from JSON.

Usage:
    python3 tools/build_captions.py captions/test-captions.json index.html [plate]

    With the optional fourth argument "plate", build the PLATE-ONLY
    variant: white page (multiply no-op), caption text invisible
    (transparent, no stroke), no raking light — and NO plate behind
    the caption words. The plate layer carries ONLY the date-card
    plates the pipeline injector adds, so the multiply blend darkens
    the footage behind the date cards and nowhere else. The caption
    divs and their tweens stay (the injectors need >=1 caption div
    and the timeline registration). Hook text is NOT injected into
    the plate variant (the wrapper passes hook_text_path=None): it
    sits over dark footage and needs no plate. Provenance: 68 Gate 4
    F1 (date-card plates, 2026-11-25). Caption word plates were live
    briefly from the 68 Gate 4 fix round 2 the same day and REMOVED
    2026-11-25 per user direction — captions keep only their native
    outline (white text + black outline), like before.

Input JSON: a list of captions, each with:
    start (seconds, float), end (seconds, float),
    text (string, 2-6 words sized by rendered width — see below,
      NO em dash),
    keyword (optional, one word from the text, highlighted in gold)
    style (optional, dedicated per-video plan): punch, standard, list,
      split, question, quick — controls size, position, entrance and
      line break. size_px (60-90, default 70), bottom_px (670-850,
      default 670, larger = higher in the safe band), break_after
      (optional word index after which to break the line).
    Durations are per-caption (human pace). A word-synced group
    (word_starts present) must be >= 0.8s, except group 0 (hook);
    a group without word_starts must be >= 1.5s. The first word of
    every caption is set visible at its start so no blank frame
    occurs at a caption change; the first caption starts at 0.0s
    and its first word_starts entry is 0.00 (first word on frame 0).
    Every word must start >= 0.17s before its group end (lesson 88,
    2 full display frames), hard floor 0.13s — with a documented
    per-caption exception mechanism (see caption_checks.py). At most
    4 groups may carry a keyword (target 3). Chunk size is decided
    by rendered WIDTH (rule 62, user correction 2026-11-24): fill
    the line up to the safe width (810px, the caption box), always
    leaving side margins, so long words never clip at the frame
    edges; about 4 words is the target, fewer for long words, more
    for short ones. Every rendered line is measured with the SAME
    Archivo Black TTF the renderer embeds, at the group's size_px.
    All of these guards live in caption_checks.py (same dir) and
    are shared with the Hormozi builder and the grouping helper,
    so all three measure the same way.

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
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] != "plate"):
        fail("usage: build_captions.py <captions.json> <output.html> [plate]")
    captions_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])
    plate_only = len(sys.argv) == 4
    captions = json.loads(captions_path.read_text(encoding="utf-8"))
    if not isinstance(captions, list) or not captions:
        fail("captions file must be a non-empty JSON list")

    # Shared guards (caption_checks.py, same dir): the token-level
    # rules — lesson-88, 0.8s floor, G0, keyword cap, width, fragments,
    # lesson-43 — measured the same way by both builders and the
    # grouping helper. A warning is a valid documented lesson-88
    # exception (the word passes, but the log must show it).
    try:
        import caption_checks as cc
    except ImportError as e:
        fail(f"caption_checks.py is required (same dir as this builder): {e}")
    project_root = Path(__file__).resolve().parent.parent
    font_path = project_root / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"
    if not font_path.exists():
        fail(f"Archivo Black font missing: {font_path} — the width assert "
             f"cannot be proven without the renderer's font")
    violations, warnings = cc.validate_captions(captions, font_path)
    for w in warnings:
        print(f"build_captions: WARNING: {w}")
    if violations:
        fail("caption validation failed:\n  " + "\n  ".join(violations))

    # Builder-specific checks (style/size/bottom ranges — the legacy
    # builder's own geometry, not shared with the Hormozi builder).
    for i, cap in enumerate(captions):
        style = cap.get("style", "standard")
        if style not in ("punch", "standard", "list", "split", "question", "quick"):
            fail(f"caption {i}: unknown style {style!r}")
        size = cap.get("size_px", 70)
        if not (60 <= float(size) <= 90):
            fail(f"caption {i}: size_px {size} outside 60-90")
        bottom = cap.get("bottom_px", 670)
        if not (670 <= float(bottom) <= 850):
            fail(f"caption {i}: bottom_px {bottom} outside 670-850 (safe band)")

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
    # Omitted in the plate variant: the layer must be pure white
    # outside the date-card plates, and the warm sweep would
    # multiply-darken as it crosses.
    if not plate_only:
        timeline_lines.append(
            f'      tl.fromTo("#light", {{x: -1080}}, {{x: 1080, duration: {total}, ease: "none"}}, 0);'
        )

    # Vendored assets, embedded so renders are reproducible offline.
    # Project root and font_path were resolved above (the width assert
    # already failed if Archivo Black is missing).
    if font_path.exists():
        font_b64 = base64.b64encode(font_path.read_bytes()).decode("ascii")
        font_face = (
            "@font-face { font-family: 'Archivo Black'; "
            f"src: url(data:font/ttf;base64,{font_b64}) format('truetype'); "
            "font-weight: 400; font-display: swap; }"
        )
    else:
        font_face = "/* Archivo Black missing, falling back to DejaVu Sans Bold */"
    # Anton is embedded too, for the date-card / hook-text injectors
    # (pipeline-v2/render/date_cards.py, hook_text.py): their CSS
    # specifies Anton 64px/72px, and without the vendored font the
    # cards would render in the DejaVu fallback. Unused when a video
    # stages no cards or hook text.
    anton_path = project_root / "assets" / "fonts" / "Anton-Regular.ttf"
    if anton_path.exists():
        anton_b64 = base64.b64encode(anton_path.read_bytes()).decode("ascii")
        anton_face = (
            "@font-face { font-family: 'Anton'; "
            f"src: url(data:font/ttf;base64,{anton_b64}) format('truetype'); "
            "font-weight: 400; font-display: swap; }"
        )
    else:
        anton_face = "/* Anton missing — date cards / hook text would fall back to DejaVu Sans Bold */"
    gsap_path = project_root / "assets" / "gsap.min.js"
    if gsap_path.exists():
        gsap_tag = f"<script>\n{gsap_path.read_text(encoding='utf-8')}\n</script>"
    else:
        gsap_tag = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>'

    # Plate-only variant (68 Gate 4 F1, 2026-11-25; caption word plates
    # REMOVED 2026-11-25 per user direction — captions keep only their
    # native outline, white text + black outline, like before): white
    # page (multiply no-op), caption text invisible (transparent, no
    # stroke), no raking light, NO plate behind caption words — so the
    # layer is white outside the date-card plates the injector adds,
    # and the multiply darkens the footage ONLY behind the cards. The
    # caption divs and their tweens stay (the injectors need >=1 caption
    # div and the timeline registration).
    page_bg = "#ffffff" if plate_only else "#0a0a0a"
    caption_color = "transparent" if plate_only else "#ffffff"
    caption_shadow = "none" if plate_only else (
        "3px 0 0 #000, -3px 0 0 #000, 0 3px 0 #000, 0 -3px 0 #000,\n"
        "          3px 3px 0 #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000,\n"
        "          0 6px 16px rgba(0, 0, 0, 0.85)"
    )
    keyword_color = "transparent" if plate_only else GOLD
    # No per-word plates in either variant (user direction 2026-11-25):
    # caption words keep only their native outline in the text layer;
    # the plate layer carries date-card plates only. The Hormozi-pattern
    # word plate (rgba(0,0,0,0.72) background + box-shadow spread) was
    # live 2026-11-25 from the 68 Gate 4 fix round 2 and is removed here.
    word_rule = ".word { display: inline-block; }"
    light_div = "" if plate_only else (
        f'      <div id="light" class="clip" data-start="0" data-duration="{total}" data-track-index="99"></div>\n'
    )

    html_doc = f"""<!doctype html>
<html lang="en" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    {gsap_tag}
    <style>
      {font_face}
      {anton_face}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        margin: 0; width: 1080px; height: 1920px; overflow: hidden;
        background: {page_bg};
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
        color: {caption_color};
        text-shadow: {caption_shadow};
      }}
      {word_rule}
      .keyword {{ color: {keyword_color}; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920">
{light_div}{chr(10).join(caption_divs)}
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
    print(f"Wrote {output_path} ({len(captions)} captions, {total}s total"
          f"{' [plate]' if plate_only else ''})")


if __name__ == "__main__":
    main()
