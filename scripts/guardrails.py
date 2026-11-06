#!/usr/bin/env python3
"""Guardrails: the basic rules the brain's scene code must obey, per format.

The rules live in guardrails.json (data, not code) so the control app
can read and change them later without a code push. This module loads
that file and falls back to the built-in defaults if it is missing or
unreadable, so the pipeline never breaks on a bad config.

Shorts and long-form are different mediums, so they get different
rules. The code writer (codegen.py) puts the format's rules in the
prompt and enforces them in validation; a beat that breaks a rule is
rejected and retried, never shipped.

Why this exists: entry 3's first render passed the HyperFrames check
but shipped a hook line cut off at the frame edge (one 10-word line
at 116px) and a closing beat with no visible text. The static check
does not catch those; these guardrails do, because they bound text
length and layout per format before the code is accepted.
"""
import json
import os

DEFAULTS = {
    "basic_rules": [
        "Use ONLY core GSAP (tl.fromTo, tl.to, tl.set). Do NOT use "
        "motionPath, ScrollTrigger, or any other plugin; they are not "
        "loaded and the check fails.",
        "Only call prepDraw or dashLen on paths, lines, polylines, "
        "circles. Never on <text> elements: text has no length, so "
        "fade it in with opacity instead of drawing it on.",
        "Never compute a tween duration from S or E as an absolute "
        "time (for example 14.6 - (S + 2.8)). Use a fixed number of "
        "seconds, or a relative length such as (E - S - 2).",
        "Every beat's timeline ends with the exit fade and hard kill "
        "(added mechanically). Do not write the exit yourself.",
        "All element ids must start with the beat id (%%ID%%-...). "
        "Never reference an id you did not define.",
        "Keep everything inside the format's canvas margins. No "
        "overflow, no overlap.",
        "No <script> tag in markup. No <!--TIMELINE--> marker.",
        "No em dashes anywhere.",
    ],
    "formats": {
        "shorts": {
            "label": "Shorts",
            "canvas": [1080, 1920],
            "base_template": "base.html",
            "big_text": {"classes": ["hook-line", "close-line"],
                         "max_words": 4, "max_chars": 24},
            "margins": {"left": 40, "right": 1040,
                        "top": 120, "bottom": 1800},
            "prompt": "FORMAT: Shorts. Vertical 1080x1920, 30 to 60 seconds.\n"
                      "- Pace is FAST. Hook in the first seconds, big and "
                      "immediate. No dead air: every beat builds, holds "
                      "briefly, then exits.\n"
                      "- BIG TEXT RULE: .hook-line (116px) and .close-line "
                      "(104px) do NOT wrap. One line holds at most 4 short "
                      "words (about 24 characters). A full sentence on one "
                      "line overflows the frame and is cut off. Break long "
                      "text into MULTIPLE short lines, one div per phrase, "
                      "stacked vertically. Never put a whole sentence on "
                      "one big line.\n"
                      "- Titles 40-44px, body 28-34px. Keep everything "
                      "inside the margins: left 40px, right 1040px, top "
                      "120px, bottom 1800px.\n"
                      "- Captions are added later in 3-4 word chunks, lower "
                      "third. Do not draw your own captions into the scene.",
        },
        "longform": {
            "label": "Long-form",
            "canvas": [1920, 1080],
            "base_template": "base-longform.html",
            "big_text": {"classes": ["hook-line", "close-line"],
                         "max_words": 6, "max_chars": 40},
            "margins": {"left": 80, "right": 1840,
                        "top": 80, "bottom": 1000},
            "prompt": "FORMAT: Long-form. Horizontal 1920x1080, 10 to 15 "
                      "minutes, built in chapters (5 parts).\n"
                      "- Pace is SLOW, with breathing room. Hold a scene "
                      "longer so the voice can finish; do not rush. At a "
                      "chapter boundary, hold the last clip 1s longer so "
                      "the voice finishes, then leave 0.5s of silence "
                      "before the next chapter's voice begins.\n"
                      "- BIG TEXT RULE: .hook-line (80px) and .close-line "
                      "(72px) do NOT wrap. One line holds at most 6 short "
                      "words (about 40 characters). A full sentence on one "
                      "line overflows the frame and is cut off. Break long "
                      "text into MULTIPLE short lines, one div per phrase, "
                      "stacked vertically. Never put a whole sentence on "
                      "one big line.\n"
                      "- Titles 60-80px, body 36-44px. The frame is wide: "
                      "side-by-side elements are fine. Keep everything "
                      "inside the margins: left 80px, right 1840px, top "
                      "80px, bottom 1000px.\n"
                      "- Characters, clothing, and environments must be "
                      "accurate to the real people, place, and era of the "
                      "story. Never modernise a historical scene.\n"
                      "- The narration ends on an open question, then 3-5 "
                      "seconds of silence. Never write a call to action.\n"
                      "- Captions are added later as SRT + burn-in. Do not "
                      "draw your own captions into the scene.",
        },
    },
}


def _load():
    """Load guardrails.json next to this module; fall back to DEFAULTS
    if it is missing or unreadable. Never crash on a bad config."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "guardrails.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return DEFAULTS
    if not isinstance(data, dict) or "formats" not in data:
        return DEFAULTS
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


# Loaded once at import; the file is read fresh on every process start,
# so a new guardrails.json is picked up by the next workflow run.
DATA = _load()
FORMATS = DATA["formats"]
BASIC_RULES = DATA.get("basic_rules", DEFAULTS["basic_rules"])


def get(fmt):
    """Return the guardrails for a format name ("shorts"/"longform").
    Unknown names fall back to shorts, never crash."""
    return FORMATS.get(fmt, FORMATS["shorts"])


def big_text_limits(fmt):
    """(max_words, max_chars) for big text lines in this format."""
    b = get(fmt)["big_text"]
    return b["max_words"], b["max_chars"]


def big_text_classes(fmt):
    """CSS classes that count as big text in this format."""
    return get(fmt)["big_text"]["classes"]
