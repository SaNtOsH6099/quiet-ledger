#!/usr/bin/env python3
"""Render Echoes caption karaoke at 24 fps (HyperFrames wrapper).

Inputs:
  --captions-json  captions.json: a list of captions measured from the
                   LOCKED narration (faster-whisper base + small, compared
                   word-for-word, disagreements flagged). Each caption:
                   {"start": 0.0, "end": 3.1, "text": "Three to five words",
                    "keyword": "five", "style": "standard",
                    "word_starts": [0.0, 0.4, 0.9, 1.5],
                    "size_px": 70, "bottom_px": 670, "break_after": 2}
  --project-dir    a HyperFrames caption project (index.html template,
                   vendored GSAP + Archivo Black font). The local project
                   lives at ~/workspace/video-tools/echoes-hyperframes/
                   and is NOT in this repo yet — see PLACEHOLDER below.
  --out            captions-24fps.mp4 (1080x1920, 24 fps)

PLACEHOLDER — read this before running:
  The local caption build (tools/build_captions.py, which turns the JSON
  into a self-contained HyperFrames composition, and
  tools/render_captions_24fps.sh, which runs
  `npx hyperframes@0.9.2 render . -o renders/captions-24fps.mp4 --fps 24
  --resolution portrait --quality delivery --keyframe-interval 2
  --low-memory-mode --workers 1`) has NOT been ported into this repo.
  This script validates the captions JSON now, and fails loudly with a
  clear message until that port lands. It does NOT invent a caption
  renderer: the Echoes look (word-by-word pop, gold keyword, safe band
  at bottom 670-850px, no em dashes, first caption at 0.0s, hold 2s+)
  lives in build_captions.py, and a re-implementation here would drift
  from the videos already shipped.

What this script DOES do today: validate the caption JSON against the
Echoes rules, so a bad caption file fails here instead of in the render.
"""
import argparse
import json
import os
import subprocess
import sys

EM_DASH = "\u2014"
STYLES = ("punch", "standard", "list", "split", "question", "quick")


def fail(msg):
    raise SystemExit(f"echoes_captions: ERROR: {msg}")


def validate(captions):
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
            if len(cap["word_starts"]) != len(words):
                fail(f"caption {i}: word_starts length != word count")
            if end - start < 0.5:
                fail(f"caption {i}: duration {end - start}s, must be >= 0.5s")
        elif end - start < 1.5:
            fail(f"caption {i}: duration {end - start}s, must be >= 1.5s")
        if prev_end is not None and start < prev_end - 1e-9:
            fail(f"caption {i}: overlaps previous caption")
        if i == 0 and start != 0.0:
            fail("first caption must start at 0.0s (no slow opening)")
        keyword = cap.get("keyword")
        if keyword:
            clean = lambda w: "".join(c for c in w if c.isalnum() or c == "'")
            if clean(keyword).lower() not in [clean(w).lower() for w in words]:
                fail(f"caption {i}: keyword {keyword!r} is not in {text!r}")
        if cap.get("style", "standard") not in STYLES:
            fail(f"caption {i}: unknown style {cap.get('style')!r}")
        size = float(cap.get("size_px", 70))
        if not 60 <= size <= 90:
            fail(f"caption {i}: size_px {size} outside 60-90")
        bottom = float(cap.get("bottom_px", 670))
        if not 670 <= bottom <= 850:
            fail(f"caption {i}: bottom_px {bottom} outside 670-850 (safe band)")
        prev_end = end
    print(f"validated {len(captions)} captions, "
          f"total {max(float(c['end']) for c in captions):.2f}s")


def main():
    parser = argparse.ArgumentParser(
        description="render Echoes captions at 24 fps (HyperFrames)")
    parser.add_argument("--captions-json", required=True)
    parser.add_argument("--project-dir", required=True,
                        help="HyperFrames caption project (to be ported)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.captions_json) as f:
        captions = json.load(f)
    validate(captions)

    build = os.path.join(args.project_dir, "tools", "build_captions.py")
    render = os.path.join(args.project_dir, "tools", "render_captions_24fps.sh")
    if not (os.path.exists(build) and os.path.exists(render)):
        fail(
            "PLACEHOLDER: HyperFrames caption project not ported yet. "
            "Port tools/build_captions.py and tools/render_captions_24fps.sh "
            "from the local project ~/workspace/video-tools/echoes-hyperframes/ "
            "into this repo (with its vendored font + GSAP), then re-run. "
            "Captions JSON validated OK; nothing was rendered."
        )
    # Ported project present: build the composition, render at 24 fps.
    subprocess.run(
        ["python3", build, args.captions_json,
         os.path.join(args.project_dir, "index.html")], check=True)
    subprocess.run(["bash", render], check=True, cwd=args.project_dir)
    rendered = os.path.join(args.project_dir, "renders", "captions-24fps.mp4")
    os.replace(rendered, args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
