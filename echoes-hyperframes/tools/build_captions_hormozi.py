#!/usr/bin/env python3
"""Build an Echoes Originals HyperFrames HORMOZI caption composition from JSON.

Usage:
    python3 tools/build_captions_hormozi.py captions/<name>.json index.html [plate]

    With the optional third argument "plate", build the PLATE-ONLY
    variant: white background, text transparent, only the dark word
    plates visible. That variant is multiply-blended over the footage
    (white = no change, dark plate = darkens), while the normal variant
    (black background, text only) is screen-blended on top. The two
    layers MUST be composited separately: a dark plate is invisible in
    a screen blend (screen can only lighten), so a single overlay with
    the plate baked in loses the plate entirely — caught 2026-11-14
    when demo v3's plate vanished over the bright vellum.

This is the NEW kinetic style, researched 2026-11-14 from current
short-form retention practice (Hormozi / MrBeast / top Shorts creators),
NOT the 55 viral style (Archivo Black, gold #FFD166, hook upper).
Differences from the viral style:
  - font Anton (condensed heavy sans), ALL-CAPS throughout
  - active word: vivid yellow #FFE600 AND a scale snap to 1.08 while it
    is spoken, then it settles white at scale 1.0
  - 1-3 words per on-screen group (tighter clusters, a visual drumbeat
    every 300-500ms on fast passages)
  - EVERYTHING centre (bottom ~1000, y 35-65% of frame) — no upper hook
  - hook word alone and huge ("UNREADABLE", 140px) for the first 3s
  - no raking light: the text snap is the only motion
  - SMART CHUNKING (user feedback 2026-11-14): the builder decides what
    to keep together and what not, from the measured word gaps. Words
    spoken < 0.20s apart are one highlight unit — a rapid burst like
    "TWO HUNDRED FORTY" highlights as ONE phrase instead of blinking
    word by word. Each word still pops in at its own measured time
    (sync exact); only the yellow highlight is chunked. Words with a
    real pause (>= 0.20s) get their own highlight, as before.
  - HEAVY outline (6px black stroke + strong drop shadow, user correction
    2026-11-14): the white words must stay readable on bright backgrounds
    such as the light vellum of the folio
  - WIDTH-AWARE WRAPPING (user correction 2026-11-14): a line must fit
    the caption container. "THE GREATEST CODEBREAKERS" at 110px
    was ~1230px wide and ran off both frame edges — the .line had
    white-space: nowrap, so it never wrapped, it just overflowed.
    Lines are now packed greedily: a line breaks when the next word
    would push its estimated width past MAX_LINE_PX, or at 3 words.
    Width estimate: Anton averages ~0.47em per character (measured
    from the overflow frame); 0.50em is used to stay safe. The
    container is 980px wide (50px clear on each side of the 1080
    frame — user rule: 50px is enough, never touch the frame sides).
    Sizes were also stepped down a little at the same time (body
    110->95, hook 120->105, hook word 140->125) — smaller, but not
    very small.
  - DARK BACKPLATE (user direction 2026-11-14, "darker shade"): each WORD
    carries its own plate (background + box-shadow spread, rgba(0,0,0,0.72),
    rounded corners), so the words read on ANY background, bright or dark.
    Per-word, NOT per-group: a group plate was tried first and left an
    empty dark area where the next word had not appeared yet. Word plates
    merge into one bar as the words pop in, and each plate appears with
    its word — no empty area, ever.

Input JSON: a list of caption groups, each with:
    start (seconds, float), end (seconds, float),
    text (string, 1-3 words, ALL-CAPS, NO em dash),
    style ("hook" or "body"),
    size_px (90-150), bottom_px (centre 950-1050),
    word_starts (REQUIRED, one measured start per word, same length
      as the word count; first group must start at 0.0).

Implementation note: HyperFrames' supported GSAP properties are
opacity, x, y, scale, scaleX, scaleY, rotation, width, height,
visibility — colour is NOT animated. So each word is rendered as two
stacked copies (a white copy and a yellow copy, same text, same box);
the yellow copy starts at opacity 0 and is switched on at the word's
start, then switched off (white back on) when the next word starts.
Only opacity/scale/y are ever tweened.

Output: a self-contained 1080x1920 HyperFrames composition (index.html)
using GSAP, following the project AGENTS.md contract:
  - every timed element has data-start and data-duration, class="clip"
  - one paused root timeline registered on window.__timelines["main"]
  - only deterministic logic, no Date.now / Math.random / network fetches:
    GSAP and the display font are vendored into this project and embedded
    in the generated HTML, so a render does not depend on a CDN at all
  - first caption starts at 0.0s: no fade-in, no static opening
"""
import base64
import html
import json
import re
import sys
from pathlib import Path

EM_DASH = "\u2014"
YELLOW = "#FFE600"
# Caption container is left:50px width:980px; a line wider than this
# overflows the frame (white-space: nowrap never wraps). Pack lines so
# none exceeds MAX_LINE_PX (estimated, Anton ~0.47em/char, 0.50 used).
# 980px = 50px clear on each side of the 1080 frame (user rule
# 2026-11-14: 50px is enough, captions never touch the frame sides).
MAX_LINE_PX = 980
CHAR_W_EM = 0.50


def fail(msg):
    raise SystemExit(f"build_captions_hormozi: ERROR: {msg}")


def clean_word(word):
    return re.sub(r"[^A-Za-z0-9']", "", word)


def main():
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        fail("usage: build_captions_hormozi.py <captions.json> <output.html> [plate]")
    captions_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])
    plate_only = len(sys.argv) == 4 and sys.argv[3] == "plate"
    captions = json.loads(captions_path.read_text(encoding="utf-8"))
    if not isinstance(captions, list) or not captions:
        fail("captions file must be a non-empty JSON list")

    prev_end = None
    for i, cap in enumerate(captions):
        text = cap.get("text", "")
        if EM_DASH in text or "--" in text:
            fail(f"caption {i}: em dash found in {text!r} (never allowed)")
        if text != text.upper():
            fail(f"caption {i}: not ALL-CAPS: {text!r}")
        words = text.split()
        if not (1 <= len(words) <= 6):
            fail(f"caption {i}: {len(words)} words, must be 1-6: {text!r}")
        start, end = float(cap["start"]), float(cap["end"])
        starts = cap.get("word_starts")
        if not starts:
            fail(f"caption {i}: word_starts required (measured spoken times)")
        if len(starts) != len(words):
            fail(f"caption {i}: word_starts length != word count")
        if end - start < 0.25:
            fail(f"caption {i}: duration {end - start}s, must be >= 0.25s")
        if prev_end is not None and start < prev_end - 1e-9:
            fail(f"caption {i}: overlaps previous caption")
        if i == 0 and start != 0.0:
            fail("first caption must start at 0.0s (no slow opening)")
        style = cap.get("style", "body")
        if style not in ("hook", "body"):
            fail(f"caption {i}: unknown style {style!r}")
        size = cap.get("size_px", 110)
        if not (90 <= float(size) <= 150):
            fail(f"caption {i}: size_px {size} outside 90-150")
        bottom = cap.get("bottom_px", 1000)
        if not (950 <= float(bottom) <= 1050):
            fail(f"caption {i}: bottom_px {bottom} outside 950-1050 (centre)")
        prev_end = end

    # READABILITY RULE (user feedback 2026-11-14): a group that flashes
    # too fast to read is merged with the next group, so the combined
    # phrase stays up long enough. A group is too fast when it gives
    # under 0.20s per word — a viewer reads about 4-5 words a second,
    # so less than that means the words flash away before they land.
    # (Strengthened 2026-11-14: the old 0.35s / 0.15s-per-word bar
    # still left fast passages unreadable, even after digits.)
    # Merging keeps every word's measured pop time (karaoke stays
    # exact); only the group boundary moves, so the phrase holds
    # longer. Only merge into a group with the same style/size/position,
    # and never past 6 words (the validation cap — a merged group
    # splits into lines of at most 3).
    merged = []
    i = 0
    while i < len(captions):
        cap = dict(captions[i])
        cap["word_starts"] = list(cap["word_starts"])
        words = cap["text"].split()
        while (
            i + 1 < len(captions)
            and captions[i + 1].get("style", "body") == cap.get("style", "body")
            and captions[i + 1].get("bottom_px", 1000) == cap.get("bottom_px", 1000)
            and (float(cap["end"]) - float(cap["start"])) / len(words) < 0.20
            and len(words) + len(captions[i + 1]["text"].split()) <= 6
        ):
            nxt = captions[i + 1]
            cap["text"] = cap["text"] + " " + nxt["text"]
            cap["end"] = nxt["end"]
            # Size may differ only because a fast group was shrunk to fit
            # one line (e.g. TWO HUNDRED FORTY at 100px vs 110px); the
            # merged group splits into lines, so take the larger size.
            cap["size_px"] = max(cap.get("size_px", 110), nxt.get("size_px", 110))
            cap["word_starts"] = cap["word_starts"] + list(nxt["word_starts"])
            words = cap["text"].split()
            i += 1
        merged.append(cap)
        i += 1
    captions = merged

    total = max(float(c["end"]) for c in captions)

    caption_divs = []
    timeline_lines = []
    for i, cap in enumerate(captions):
        start, end = float(cap["start"]), float(cap["end"])
        words = cap["text"].split()
        size = cap.get("size_px", 110)
        bottom = cap.get("bottom_px", 1000)
        word_starts = [float(s) for s in cap["word_starts"]]
        # Lines are packed greedily: at most 3 words AND at most
        # MAX_LINE_PX estimated width. A wide group (e.g. THE GREATEST
        # CODEBREAKERS) becomes two lines instead of running off the
        # frame. Word ids use the global word index, so the GSAP
        # timeline below is unchanged.
        line_groups = []
        cur = []
        for j, w in enumerate(words):
            if cur:
                trial = cur + [j]
                trial_text = " ".join(words[k] for k in trial)
                if len(trial) > 3 or len(trial_text) * size * CHAR_W_EM > MAX_LINE_PX:
                    line_groups.append(cur)
                    cur = [j]
                else:
                    cur = trial
            else:
                cur = [j]
        if cur:
            line_groups.append(cur)
        lines = []
        for lg in line_groups:
            line_spans = []
            for j in lg:
                w = html.escape(words[j])
                line_spans.append(
                    f'<span class="word" id="c{i}w{j}">'
                    f'<span class="wl" id="c{i}w{j}w">{w}</span>'
                    f'<span class="yl" id="c{i}w{j}y">{w}</span>'
                    f"</span>"
                )
            lines.append(f'<div class="line">{" ".join(line_spans)}</div>')
        caption_divs.append(
            f'      <div class="clip caption" id="caption{i}" '
            f'data-start="{start}" data-duration="{end - start}" '
            f'data-track-index="{i}" style="font-size: {size}px; bottom: {bottom}px;">'
            f'{"".join(lines)}</div>'
        )
        # SMART CHUNKING (user feedback 2026-11-14): words spoken close
        # together (< 0.20s apart) are one highlight unit — a rapid burst
        # like "TWO HUNDRED FORTY" (0.10s apart) highlights as ONE phrase
        # instead of blinking word by word. Each word still pops in at its
        # own measured time (sync stays exact); only the yellow highlight
        # is chunked — a word stays yellow until its CHUNK ends, then the
        # whole chunk turns white together. Words with a real pause
        # (>= 0.20s) get their own highlight, as before.
        # next_chunk_start[j] = start time of the next chunk after word j,
        # or None if word j is in the group's last chunk.
        next_chunk_start = [None] * len(words)
        for j in range(len(words)):
            for k in range(j + 1, len(words)):
                if word_starts[k] - word_starts[k - 1] >= 0.20:
                    next_chunk_start[j] = word_starts[k]
                    break
        # SHOW-ALL MODE (user feedback 2026-11-14): for a very fast
        # BODY phrase (under 0.25s per word) the words do NOT pop in
        # one by one — the whole phrase appears at once at the group
        # start, and only the yellow highlight moves word by word. A
        # fast burst read word-by-word flashes away before the eye can
        # follow it; seeing the whole phrase up front lets the viewer
        # read ahead while the highlight tracks the narration. The
        # hook keeps its punchy word-by-word pop (passed in the demo).
        # EXPLICIT OVERRIDE (67, Gate 1 red team 2026-11-17): a body
        # phrase can also carry "mode": "show-all" in the JSON. The
        # 0.25s/word heuristic is a trigger, not the whole rule — a
        # phrase at 203 wpm (0.295s/word) is still too fast for
        # word-by-word pop, and the reviewer for that video said so.
        # The validator ignores the extra key, so the file still
        # validates; the render honours it here and in the local build.
        is_fast = cap.get("style") == "body" and (
            (end - start) / len(words) < 0.25 or cap.get("mode") == "show-all")
        for j in range(len(words)):
            t = word_starts[j]
            pop_t = start if is_fast else t
            # Snap in at the pop time (group start for a fast phrase,
            # the word's own spoken time otherwise), born yellow AND
            # big: sharp scale snap 0.6 -> 1.08, then settle to 1.0.
            # 1.08 (not 1.12): at 1.12 the active word grew over its
            # neighbour (snapshot at 5.6s showed HUNDRED covering TWO's O).
            timeline_lines.append(
                f'      tl.fromTo("#c{i}w{j}", '
                f'{{opacity: 0, y: 12, scale: 0.6}}, '
                f'{{opacity: 1, y: 0, scale: 1.08, duration: 0.10, ease: "back.out(3)"}}, {pop_t:.2f});'
            )
            timeline_lines.append(
                f'      tl.to("#c{i}w{j}", {{scale: 1, duration: 0.10, ease: "power2.out"}}, {pop_t + 0.10:.2f});'
            )
            timeline_lines.append(
                f'      tl.set("#c{i}w{j}y", {{opacity: 1}}, {t:.2f});'
            )
            timeline_lines.append(
                f'      tl.set("#c{i}w{j}w", {{opacity: 0}}, {t:.2f});'
            )
            # A word turns white when its CHUNK ends (the next chunk
            # starts), not when the next word starts. The last chunk
            # of a group stays yellow until the group exits.
            t_next = next_chunk_start[j]
            if t_next is not None:
                timeline_lines.append(
                    f'      tl.set("#c{i}w{j}y", {{opacity: 0}}, {t_next:.2f});'
                )
                timeline_lines.append(
                    f'      tl.set("#c{i}w{j}w", {{opacity: 1}}, {t_next:.2f});'
                )
        # Fast exit at the end of the caption: a hard cut, not a long fade.
        # Short groups get a proportionally shorter exit so the word is
        # actually visible before it leaves.
        exit_dur = min(0.12, (end - start) * 0.3)
        timeline_lines.append(
            f'      tl.to("#caption{i}", {{opacity: 0, duration: {exit_dur:.2f}}}, {end - exit_dur:.2f});'
        )

    # Vendored assets, embedded so renders are reproducible offline.
    # Project root is the parent of tools/.
    project_root = Path(__file__).resolve().parent.parent
    font_path = project_root / "assets" / "fonts" / "Anton-Regular.ttf"
    if font_path.exists():
        font_b64 = base64.b64encode(font_path.read_bytes()).decode("ascii")
        font_face = (
            "@font-face { font-family: 'Anton'; "
            f"src: url(data:font/ttf;base64,{font_b64}) format('truetype'); "
            "font-weight: 400; font-display: swap; }"
        )
    else:
        font_face = "/* Anton missing, falling back to DejaVu Sans Bold */"
    gsap_path = project_root / "assets" / "gsap.min.js"
    if gsap_path.exists():
        gsap_tag = f"<script>\n{gsap_path.read_text(encoding='utf-8')}\n</script>"
    else:
        gsap_tag = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>'

    # Plate-only variant: white page (multiply no-op), text invisible,
    # plates only. Normal variant: near-black page (screen no-op), text
    # with the heavy stroke, no plate (the plate lives in the other layer).
    page_bg = "#ffffff" if plate_only else "#0a0a0a"
    caption_shadow = (
        "none" if plate_only else
        "6px 0 0 #000, -6px 0 0 #000, 0 6px 0 #000, 0 -6px 0 #000,\n"
        "          6px 6px 0 #000, -6px -6px 0 #000, 6px -6px 0 #000, -6px 6px 0 #000,\n"
        "          0 10px 24px rgba(0, 0, 0, 0.95)"
    )
    wl_color = "transparent" if plate_only else "#ffffff"
    yl_color = "transparent" if plate_only else YELLOW
    word_plate = (
        "background: rgba(0, 0, 0, 0.72);\n"
        "        border-radius: 0.14em;\n"
        "        box-shadow: 0 0 0 0.10em rgba(0, 0, 0, 0.72);"
        if plate_only else ""
    )

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
        background: {page_bg};
      }}
      #root {{ width: 100%; height: 100%; position: relative; }}
      .caption {{
        position: absolute; left: 50px; width: 980px;
        display: flex; flex-direction: column; align-items: center;
        gap: 0.05em;
        text-align: center; word-spacing: 0.15em;
        font-family: "Anton", "DejaVu Sans", "Arial Black", sans-serif;
        font-size: 110px; font-weight: 400; line-height: 1.05;
        letter-spacing: 0.01em;
        color: #ffffff;
        text-shadow: {caption_shadow};
      }}
      .line {{ white-space: nowrap; }}
      .word {{
        display: inline-block; position: relative;
        {word_plate}
      }}
      .wl {{ display: inline-block; color: {wl_color}; }}
      .yl {{ display: inline-block; position: absolute; left: 0; top: 0; color: {yl_color}; opacity: 0; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920">
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
    n_hook = sum(1 for c in captions if c.get("style") == "hook")
    print(f"Wrote {output_path} ({len(captions)} groups, {n_hook} hook, "
          f"{len(captions) - n_hook} body, {total}s total)")


if __name__ == "__main__":
    main()
