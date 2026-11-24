#!/usr/bin/env python3
"""Shared caption checks for Echoes Originals (rule 62 phrase model).

Single source of truth for the token-level caption guards, imported by
both builders (legacy build_captions.py and Hormozi
build_captions_hormozi.py) and by the grouping helper (group_phrases.py)
so all three measure the same way. The RMS-based pause audit (TEST 1 /
TEST 2 / TEST 2b, which needs audio) stays in the Hormozi builder — it
is NOT ported here; only the token-level checks live in this module.

Rules enforced (all return a list of violation strings; empty = clean):
  - lesson-88: every word must start >= 0.17s before its group end
    (2 full display frames), hard floor 0.13s (1 full frame). A word
    in [0.13, 0.17) passes ONLY with a documented per-caption
    exception (see check_lesson88); below 0.13s never passes.
  - lesson-43: consecutive word starts must fall in different 24fps
    frames (checked on the DISPLAY word_starts the renderer uses).
  - durations: a word-synced group (word_starts present) must be
    >= 0.8s, except group 0 (hook) which keeps the old 0.5s floor;
    a group without word_starts must be >= 1.5s (old human-pace rule).
  - G0: the first group starts at 0.0 and its first word_starts entry
    is 0.00 (first word visible on frame 0).
  - keyword cap: at most 4 groups may carry a keyword (target 3);
    a keyword must be a word in its group's text.
  - width: every rendered line <= 810px (the legacy caption box),
    at most 2 lines per group, measured with the SAME Archivo Black
    TTF the renderer embeds, at the group's size_px, including the
    -0.01em letter-spacing the renderer applies. A group with a
    break_after renders its forced lines; without one it auto-wraps.
  - fragments: 2-6 words per group, >= 1 content word, never a
    1-word tail and never a zero-content-word group.
  - overlap: no group starts before the previous group ends.
  - span/boundary (needs a pause list — used by the helper, which has
    one): no group spans a pause > 0.6s unless the pause is a
    producer-asserted deliberate pause (<= ~1.2s); every pause >= 0.5s
    is a group boundary (no group holds tokens on both sides of one).

Font measurement: PIL + the Archivo Black TTF. The font path is an
argument (default: assets/fonts/ArchivoBlack-Regular.ttf next to the
calling builder's project root) so the check runs wherever the
builder runs, including the GitHub runner (Pillow is in
requirements/base.txt).
"""
import re
from pathlib import Path

from PIL import ImageFont

MIN_DURATION = 0.8        # non-hook word-synced groups (group 0 exempt)
MIN_DURATION_HOOK = 0.5   # group 0 floor (old rule, kept)
MIN_DURATION_NOSYNC = 1.5  # groups without word_starts (old rule, kept)
MIN_LAST_GAP = 0.17       # lesson-88 bar: 2 full display frames
MIN_LAST_GAP_FLOOR = 0.13  # lesson-88 hard floor: 1 full frame
MAX_KEYWORD_GROUPS = 4    # fail if more groups carry a keyword (target 3)
SAFE_LINE_PX = 810        # legacy caption box width (left 90px)
MAX_LINES = 2             # a group renders as at most 2 lines
MIN_WORDS = 2
MAX_WORDS = 6
LETTER_SPACING_EM = -0.01
SPAN_ALLOWANCE = 0.6      # a group may hold at most this much of a pause
SPAN_CAP = 1.2            # asserted deliberate pauses may hold up to this

FUNCTION_WORDS = set("""a an the and or but if then else when while as at by for
with without within upon per via of to in on out into over under after before
between through during about against is am are was were be been being have
has had do does did will would can could shall should may might must
i you he she it we they me him her us them my your his its our their this
that these those there here what which who whom whose how why not no yes
all any each few more most other some such only own same too very just also
even still yet so than then once twice""".split())

# The GLUE set is what is_content() uses for the fragment test: pure
# glue with no referential meaning (articles, prepositions,
# conjunctions, auxiliaries, pure particles). Pronouns and indefinite
# determiners (it, they, any, some, all, ...) are NOT glue — they
# refer to entities, so a chunk made of them ('ANY OF IT', #47 G27)
# is a real noun phrase, not a fragment. FUNCTION_WORDS above is the
# wider set (used by the helper for boundary decisions); is_content()
# uses GLUE only.
GLUE_WORDS = set("""a an the and or but if then else when while as at by for
with without within upon per via of to in on out into over under after before
between through during about against is am are was were be been being have
has had do does did will would can could shall should may might must
then once twice so than very just also even still yet not no yes too""".split())

# A group must not END on one of these: the word takes a complement
# that lives in the next group (an article's noun, a preposition's
# object, a conjunction's clause), so the boundary is not a phrase
# boundary. Auxiliaries and pronouns are deliberately NOT in this set:
# moving one alone creates a worse fragment — those stay for the
# producer (see AUX_FLAG, which only flags them).
TRAILING_BAD = set("""a an the of to in on at by for with through from into
over under after before and or but so when while if that as than its their
our your my his""".split())

# Auxiliaries/modals a group must not end on either: the main verb
# that follows lives in the next group, so the verb phrase is split.
# The copula (be/is/are/was/were/am) is excluded: it can legitimately
# end a clause ('THAT IS WHAT IT IS').
AUX_FLAG = set("""had have has been do does did will would can could
shall should may might must""".split())

_font_cache = {}


def clean_token(word):
    return re.sub(r"[^A-Za-z0-9']", "", word)


def is_content(word):
    """A content word carries referential meaning (a noun, verb,
    adjective, pronoun, or indefinite determiner). Pure glue
    (articles, prepositions, conjunctions, auxiliaries, particles)
    does not. Used for the fragment test: a group with zero content
    words is a meaningless fragment."""
    w = clean_token(word).lower()
    if not w:
        return False
    if w.replace(",", "").replace(".", "").isdigit():
        return True
    return w not in GLUE_WORDS


def font_at(size_px, font_path):
    key = (int(size_px), str(font_path))
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(font_path), int(size_px))
    return _font_cache[key]


def line_width(text, size_px, font_path):
    """Rendered width of one line at size_px, incl. -0.01em tracking."""
    w = font_at(size_px, font_path).getlength(text)
    w += max(0, len(text) - 1) * (LETTER_SPACING_EM * size_px)
    return w


def wrap_lines(words, size_px, font_path):
    """Greedy CSS-like wrap of words into lines of <= SAFE_LINE_PX.
    Returns a list of word-index lists (indices into `words`)."""
    lines, cur = [], []
    for idx, w in enumerate(words):
        trial = cur + [idx]
        text = " ".join(words[k] for k in trial)
        if cur and line_width(text, size_px, font_path) > SAFE_LINE_PX:
            lines.append(cur)
            cur = [idx]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _exc_for(cap, word, gap):
    """Return the matching documented lesson-88 exception for this
    word, or None. An exception is valid only if it names this word,
    its stated gap matches the measured gap within 0.01s, and the
    measured gap is >= the 0.13s floor (below the floor no exception
    is possible — 0 full-brightness frames is the defect)."""
    for exc in cap.get("lesson88_exceptions", []) or []:
        if clean_token(exc.get("word", "")).lower() != clean_token(word).lower():
            continue
        if abs(float(exc.get("gap", -1)) - gap) > 0.01:
            return ("stale", exc)
        if gap < MIN_LAST_GAP_FLOOR - 1e-9:
            return ("below-floor", exc)
        return ("ok", exc)
    return None


def check_lesson88(captions):
    """Lesson-88: every word >= 0.17s before its group end (bar),
    >= 0.13s hard floor. Returns (violations, warnings). A warning
    is a valid documented exception (the word passes, but the log
    must show it)."""
    bad, warnings = [], []
    for i, cap in enumerate(captions):
        starts = cap.get("word_starts")
        if not starts:
            continue
        end = float(cap["end"])
        words = cap["text"].split()
        for j, s in enumerate(starts):
            gap = end - float(s)
            if gap >= MIN_LAST_GAP - 1e-9:
                continue
            word = words[j] if j < len(words) else "?"
            match = _exc_for(cap, word, gap)
            if match and match[0] == "ok":
                warnings.append(
                    f"caption {i} {cap['text']!r} word {word!r} at "
                    f"{float(s):.2f} is {gap:.2f}s before the end — "
                    f"below the 0.17s bar, PASSES on documented "
                    f"exception: {match[1].get('reason', '')}")
                continue
            if match and match[0] == "stale":
                bad.append(
                    f"caption {i} {cap['text']!r} word {word!r}: "
                    f"lesson-88 exception states gap "
                    f"{float(match[1].get('gap', -1)):.2f}s but measured "
                    f"gap is {gap:.2f}s — stale exception, regroup the word")
                continue
            if match and match[0] == "below-floor":
                bad.append(
                    f"caption {i} {cap['text']!r} word {word!r} at "
                    f"{float(s):.2f} is {gap:.2f}s before the end — below "
                    f"the 0.13s floor; no exception is possible (0 "
                    f"full-brightness frames), regroup it")
                continue
            floor = "floor" if gap < MIN_LAST_GAP_FLOOR - 1e-9 else "bar"
            bad.append(
                f"lesson 88: caption {i} {cap['text']!r} word {word!r} "
                f"at {float(s):.2f} is {gap:.2f}s ({gap * 24:.2f} frames) "
                f"before the group end {end:.2f} — below the "
                f"{MIN_LAST_GAP_FLOOR if floor == 'floor' else MIN_LAST_GAP}s "
                f"{floor} for "
                f"{'1' if floor == 'floor' else '2'} full-brightness "
                f"frame(s); regroup it to the next group")
    return bad, warnings


def check_lesson43(captions):
    """Lesson-43: consecutive word starts (DISPLAY starts, as the
    renderer uses them) must fall in different 24fps frames."""
    bad = []
    prev = None
    for i, cap in enumerate(captions):
        for j, st in enumerate(cap.get("word_starts") or []):
            st = float(st)
            word = cap["text"].split()[j] if j < len(cap["text"].split()) else "?"
            if prev is not None and int(prev[1] * 24) >= int(st * 24):
                bad.append(
                    f"caption {i}: lesson 43: {prev[0]!r} {prev[1]:.2f} "
                    f"and {word!r} {st:.2f} pop on the same frame "
                    f"(frame {int(st * 24)}) — settle the onset")
            prev = (word, st)
    return bad


def check_durations(captions):
    bad = []
    for i, cap in enumerate(captions):
        dur = float(cap["end"]) - float(cap["start"])
        if cap.get("word_starts"):
            floor = MIN_DURATION_HOOK if i == 0 else MIN_DURATION
            if dur < floor - 1e-9:
                bad.append(
                    f"caption {i} {cap['text']!r}: duration {dur:.2f}s, "
                    f"must be >= {floor}s"
                    + (" (hook group)" if i == 0 else ""))
        elif dur < MIN_DURATION_NOSYNC - 1e-9:
            bad.append(
                f"caption {i} {cap['text']!r}: duration {dur:.2f}s, "
                f"must be >= {MIN_DURATION_NOSYNC}s (no word_starts)")
    return bad


def check_g0(captions):
    bad = []
    if not captions:
        return ["captions file must be a non-empty JSON list"]
    if float(captions[0]["start"]) != 0.0:
        bad.append("first caption must start at 0.0s (no slow opening)")
    starts = captions[0].get("word_starts")
    if starts and float(starts[0]) != 0.0:
        bad.append(
            "first caption's first word_starts entry must be 0.0 "
            f"(first word visible on frame 0), got {float(starts[0]):.2f}")
    return bad


def check_keywords(captions):
    bad = []
    n_kw = 0
    for i, cap in enumerate(captions):
        keyword = cap.get("keyword")
        if not keyword:
            continue
        n_kw += 1
        words = cap["text"].split()
        if clean_token(keyword).lower() not in [
                clean_token(w).lower() for w in words]:
            bad.append(
                f"caption {i}: keyword {keyword!r} is not a word in "
                f"{cap['text']!r}")
    if n_kw > MAX_KEYWORD_GROUPS:
        bad.append(
            f"{n_kw} groups carry a keyword, max {MAX_KEYWORD_GROUPS} "
            f"(target 3)")
    return bad


def check_width(captions, font_path):
    """Width: every rendered line <= 810px, at most 2 lines per group.
    A group with break_after renders its forced lines; without one it
    auto-wraps (greedy, same as the browser)."""
    bad = []
    for i, cap in enumerate(captions):
        words = cap["text"].split()
        size = cap.get("size_px", 70)
        ba = cap.get("break_after")
        if ba is not None:
            ba = int(ba)
            if not (1 <= ba < len(words)):
                bad.append(
                    f"caption {i} {cap['text']!r}: break_after {ba} "
                    f"outside 1..{len(words) - 1}")
                continue
            lines = [words[:ba], words[ba:]]
        else:
            idx_lines = wrap_lines(words, size, font_path)
            lines = [[words[k] for k in line] for line in idx_lines]
        if len(lines) > MAX_LINES:
            bad.append(
                f"caption {i} {cap['text']!r}: renders as {len(lines)} "
                f"lines, max {MAX_LINES}")
        for li, line in enumerate(lines):
            lw = line_width(" ".join(line), size, font_path)
            if lw > SAFE_LINE_PX + 1e-9:
                bad.append(
                    f"caption {i} {cap['text']!r}: line {li} "
                    f"({' '.join(line)!r}) is {lw:.0f}px > {SAFE_LINE_PX}px")
    return bad


def check_fragments(captions):
    bad = []
    for i, cap in enumerate(captions):
        words = cap["text"].split()
        if not (MIN_WORDS <= len(words) <= MAX_WORDS):
            bad.append(
                f"caption {i} {cap['text']!r}: {len(words)} words, "
                f"must be {MIN_WORDS}-{MAX_WORDS}")
        if not any(is_content(w) for w in words):
            bad.append(
                f"caption {i} {cap['text']!r}: zero content words")
    return bad


def check_overlap(captions):
    bad = []
    prev_end = None
    for i, cap in enumerate(captions):
        start = float(cap["start"])
        if prev_end is not None and start < prev_end - 1e-9:
            bad.append(f"caption {i}: overlaps previous caption")
        prev_end = float(cap["end"])
    return bad


def check_no_em_dash(captions):
    bad = []
    for i, cap in enumerate(captions):
        text = cap.get("text", "")
        if "\u2014" in text or "--" in text:
            bad.append(
                f"caption {i}: em dash found in {text!r} (never allowed)")
    return bad


def check_one_span(idx, text, start, end, pauses, span_exceptions=()):
    """Span check for one group: its display interval overlaps any
    pause inside it. The overlap must be <= 0.6s, or <= ~1.2s for a
    producer-asserted deliberate pause."""
    bad = []
    for a, b in pauses:
        overlap = min(end, b) - max(start, a)
        if overlap <= SPAN_ALLOWANCE + 1e-9:
            continue
        asserted = any(
            abs(pa - a) <= 0.05 and abs(pb - b) <= 0.05
            for pa, pb in (e["pause"] for e in span_exceptions))
        if overlap > SPAN_CAP + 1e-9:
            bad.append(
                f"caption {idx} {text!r}: holds {overlap:.2f}s "
                f"over pause {a:.2f}-{b:.2f} — over the "
                f"{SPAN_CAP}s span cap")
        elif not asserted:
            bad.append(
                f"caption {idx} {text!r}: holds {overlap:.2f}s "
                f"over pause {a:.2f}-{b:.2f} ({b - a:.2f}s) — over "
                f"the {SPAN_ALLOWANCE}s span allowance, not asserted")
    return bad


def check_spans(captions, pauses, span_exceptions=()):
    """Span/boundary check (needs a pause list — used by the grouping
    helper, which has one; the builders do not carry pauses, so they
    do not call this). A group holds its phrase until the next group
    pops, so its display interval overlaps any pause inside it. The
    overlap must be <= 0.6s, or <= ~1.2s for a producer-asserted
    deliberate pause. No group may hold tokens on both sides of a
    pause >= 0.5s (a pause is a group boundary)."""
    bad = []
    for i, cap in enumerate(captions):
        bad += check_one_span(
            i, cap["text"], float(cap["start"]), float(cap["end"]),
            pauses, span_exceptions)
    return bad


def check_pause_boundaries(tokens, spans, pauses):
    """Every pause >= 0.5s must be a group boundary: no span may hold
    tokens on both sides of one. `tokens` is the flat token list
    (each with a 'start'); `spans` is the list of (start_idx,
    end_idx_exclusive) token spans."""
    bad = []
    for a, b in pauses:
        if b - a < 0.5 - 1e-9:
            continue
        for k, (s, e) in enumerate(spans):
            starts = [tokens[t]["start"] for t in range(s, e)]
            before = [t for t in starts if t < a]
            after = [t for t in starts if t >= b - 1e-9]
            if before and after:
                bad.append(
                    f"group {k} holds tokens on both sides of pause "
                    f"{a:.2f}-{b:.2f} — a pause is a group boundary")
                break
    return bad


def check_word_starts_length(captions):
    """Structural check: word_starts, when present, must have exactly
    one entry per word in the text."""
    bad = []
    for i, cap in enumerate(captions):
        starts = cap.get("word_starts")
        if starts and len(starts) != len(cap["text"].split()):
            bad.append(
                f"caption {i}: word_starts length {len(starts)} != "
                f"word count {len(cap['text'].split())}")
    return bad


def validate_captions(captions, font_path):
    """Run every check the legacy builder enforces. Returns
    (violations, warnings)."""
    bad = []
    bad += check_no_em_dash(captions)
    bad += check_word_starts_length(captions)
    bad += check_fragments(captions)
    bad += check_durations(captions)
    bad += check_overlap(captions)
    bad += check_g0(captions)
    bad += check_keywords(captions)
    bad += check_width(captions, font_path)
    bad88, warn88 = check_lesson88(captions)
    bad += bad88
    bad += check_lesson43(captions)
    return bad, warn88
