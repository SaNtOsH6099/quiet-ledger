#!/usr/bin/env python3
"""Build an Echoes Originals HyperFrames HORMOZI caption composition from JSON.

Usage:
    python3 tools/build_captions_hormozi.py captions/<name>.json index.html [plate] [--mix <narration-mix.wav>]

    With the optional third argument "plate", build the PLATE-ONLY
    variant: white background, text transparent, only the dark word
    plates visible. That variant is multiply-blended over the footage
    (white = no change, dark plate = darkens), while the normal variant
    (black background, text only) is screen-blended on top. The two
    layers MUST be composited separately: a dark plate is invisible in
    a screen blend (screen can only lighten), so a single overlay with
    the plate baked in loses the plate entirely — caught 2026-11-14
    when demo v3's plate vanished over the bright vellum.

    With --mix, run the PAUSE AUDIT (lesson 41) on the JSON's
    word_starts against the locked narration mix BEFORE writing any
    HTML — a bad onset fails the build here, not at Gate 3. Pass the
    mix whenever it exists; skipping it prints a warning and is the
    only way a mistimed word reaches the renderer.

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

PAUSE AUDIT (lesson 41, --mix only; Gate 3 fail #1 video 65,
refined fail #2). Whisper smears a word's start back to the previous
word's end across a pause, and lands soft-onset words on the vowel
nucleus instead of the onset — base and small can agree and still
both be wrong (AND 60.60 lit during a full second of silence;
TO 50.18 was 0.29s late: the /t/ vowel begins at 49.89, after
SOUTH's /th/ decays to ~0.001-0.02 at 49.77-49.88; Whisper keyed
on the vowel peak 0.209 at 50.21). RMS is the arbiter. From the mix
(0.02s bins): silence = RMS < 0.0015, regions >= 0.4s.
  - TEST 1 (fails the build): no word start inside a silence more
    than 0.15s before its end.
  - TEST 2 (prints candidates for manual RMS review): any word whose
    span contains a >=0.4s silence — spoken BEFORE it (start correct)
    or AFTER it (start wrong, correct start = silence end).
  - TEST 2b (fails the build): a word can be "before the silence"
    and STILL have its start wrong. Every TEST 2 candidate's onset
    is RMS-verified by scan-back: from the claimed start, walk back
    up to 0.34s for a quiet run (>=4 consecutive 0.02s bins < 0.02);
    the onset estimate is the first bin after that run whose RMS is
    >= 0.03 (that bin may straddle the onset) with the next 3 bins
    >= 0.05. If the estimate differs from the claimed start by
    >0.15s, the start is wrong. Validated on 65: pre-fix it flagged
    TO (estimate 49.88 vs claimed 50.18, diff -0.30s) and passed
    after (49.88 vs 49.89, diff -0.01s).

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
import subprocess
import sys
from pathlib import Path

import numpy as np

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


def pause_audit(tokens, mix_path):
    """Systematic pause audit (lesson 41; ported from video 65's
    builder, work/build_65_captions.py — same thresholds, same code).

    tokens: list of (word, start, end); end of each word is the next
    word's start, last word's end is the last group's end.
    mix_path: the locked narration mix (the single master clock).

    TEST 1 (fails the build): no word start may fall inside a >=0.4s
    silence (RMS < 0.0015 in 0.02s bins) more than 0.15s before its end.
    TEST 2 (prints candidates for manual RMS review): any word whose span
    contains a >=0.4s silence. The word is spoken BEFORE the silence
    (start correct) or AFTER it (start wrong, correct start = silence end).
    TEST 2b (fails the build, fail #2 refinement): a word can be "before
    the silence" and STILL have its start wrong — Whisper lands a
    soft-onset word on its vowel peak, not its onset. So every TEST 2
    candidate's onset is RMS-verified by scan-back: from the claimed
    start, walk back up to 0.34s for a quiet run (>=4 consecutive 0.02s
    bins < 0.02); the onset estimate is the first bin after that run
    with RMS >= 0.03 (the bin may straddle the onset) and the next 3
    bins >= 0.05. If the estimate differs from the claimed start by
    >0.15s, the start is wrong.
    """
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mix_path),
                          "-f", "s16le", "-ac", "1", "-ar", "24000", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    sr, step = 24000, 0.02
    n = int(len(x) / sr / step)
    rms = np.array([float(np.sqrt(np.mean(
        x[int(i * step * sr):int((i + 1) * step * sr)] ** 2)))
        for i in range(n)])
    quiet = rms < 0.0015
    regions = []
    i = 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) * step >= 0.4:
                regions.append((round(i * step, 2), round(j * step, 2)))
            i = j
        else:
            i += 1
    for w, s, e in tokens:
        for a, b in regions:
            if a + 0.02 < s < b - 0.15:
                fail(
                    f"pause audit TEST 1: {w} at {s:.2f} inside silence "
                    f"{a:.2f}-{b:.2f} (silence ends {b - s:.2f}s later)")
    print(f"pause audit TEST 1 passed ({len(regions)} silence regions >= 0.4s)")
    for w, s, e in tokens:
        for a, b in regions:
            if s < a and b < e:
                print(f"pause audit TEST 2 candidate (manual RMS decision): "
                      f"{w} span {s:.2f}-{e:.2f} contains silence {a:.2f}-{b:.2f}")
    # TEST 2b: RMS-verify the onset of every TEST 2 candidate by scan-back.
    for w, s, e in tokens:
        for a, b in regions:
            if not (s < a and b < e):
                continue
            si = int(s / step)
            est = None
            j = si - 1
            while j >= max(0, si - 17):  # up to 0.34s back
                if j - 3 >= 0 and all(rms[k] < 0.02 for k in range(j - 3, j + 1)):
                    k = j + 1
                    # bin k may straddle the onset (quiet + loud halves), so
                    # it only needs >= 0.03; the next 3 bins must be >= 0.05.
                    if k + 3 < n and rms[k] >= 0.03 and all(
                            rms[m] >= 0.05 for m in range(k + 1, k + 4)):
                        est = round(k * step, 2)
                    break
                j -= 1
            if est is None:
                print(f"pause audit TEST 2b: {w} at {s:.2f} — no quiet run "
                      f"before start, onset not scan-back-verifiable")
            else:
                flag = "FAIL" if abs(est - s) > 0.15 else "ok"
                print(f"pause audit TEST 2b: {w} at {s:.2f} — onset estimate "
                      f"{est:.2f} (diff {est - s:+.2f}s) [{flag}]")
                if abs(est - s) > 0.15:
                    fail(
                        f"pause audit TEST 2b: {w} start {s:.2f} is "
                        f"{s - est:.2f}s after its RMS onset {est:.2f} "
                        f"(Whisper put it on the vowel peak)")


def main():
    args = sys.argv[1:]
    mix_path = None
    if "--mix" in args:
        mi = args.index("--mix")
        if mi + 1 >= len(args):
            fail("usage: build_captions_hormozi.py <captions.json> <output.html> [plate] [--mix <mix.wav>]")
        mix_path = Path(args[mi + 1])
        del args[mi:mi + 2]
    if len(args) < 2 or len(args) > 3:
        fail("usage: build_captions_hormozi.py <captions.json> <output.html> [plate] [--mix <mix.wav>]")
    captions_path, output_path = Path(args[0]), Path(args[1])
    plate_only = len(args) == 3 and args[2] == "plate"
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

    # LESSON 43 (Gate 3 FAIL #1, video 68, 2026-11-18): no duplicate
    # starts — consecutive word starts must fall in different 24fps
    # frames, or the renderer treats same-frame words as one highlight
    # unit and lights them yellow together. (68 v1: base Whisper gave
    # AND as a zero-duration token, so AND and HER shared the start
    # 55.82 and popped on the same frame.) The enforceable test is no
    # duplicate starts + each word pops on its own frame at its own
    # measured time; a sub-0.20s chunk holding yellow together is the
    # documented SMART CHUNKING behaviour, not a defect.
    prev_word = None  # (word, caption index, start)
    for i, cap in enumerate(captions):
        for j, s in enumerate(cap["word_starts"]):
            s = float(s)
            if prev_word is not None and int(prev_word[2] * 24) >= int(s * 24):
                fail(
                    f"lesson 43: {prev_word[0]!r} {prev_word[2]:.2f} and "
                    f"{cap['text'].split()[j]!r} {s:.2f} pop on the same "
                    f"frame (frame {int(s * 24)}) — settle the onset"
                )
            prev_word = (cap["text"].split()[j], i, s)

    # PAUSE AUDIT (lesson 41) — only when --mix is given. Flatten the
    # groups to (word, start, end). A word's end is the next word's
    # start, EXCEPT the last word of a group, whose end is the group's
    # end: the per-video builder caps a group end at the last word's
    # true end when the gap after it is >= 0.5s, so the group end IS
    # the true end exactly where a pause follows. Using the next
    # word's start for group-final words instead would stretch their
    # span across the following pause and invent false TEST 2
    # candidates (65 v3: BEIJING 14.94-16.48 would contain the silence
    # 15.44-16.44 and TEST 2b would scan back across "for" onto
    # "bound"'s onset, 14.68 — a false FAIL on a correct file).
    if mix_path is not None:
        flat = []
        for cap in captions:
            words = cap["text"].split()
            for j, (w, s) in enumerate(zip(words, cap["word_starts"])):
                if j == len(words) - 1:
                    e = float(cap["end"])
                else:
                    e = float(cap["word_starts"][j + 1])
                flat.append((w, float(s), e))
        pause_audit(flat, mix_path)
    else:
        print("WARNING: no --mix given, pause audit (lesson 41, TEST 1 / "
              "TEST 2b) SKIPPED — a mistimed word will reach the renderer")

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
        # validates; the render honours it here and in the repo port.
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
