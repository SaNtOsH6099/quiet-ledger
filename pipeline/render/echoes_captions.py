#!/usr/bin/env python3
"""Render Echoes caption karaoke at 24 fps (HyperFrames wrapper).

Inputs:
  --captions-json  captions.json: a list of caption groups measured
                   from the LOCKED narration (faster-whisper base +
                   small, compared word-for-word, disagreements
                   flagged). Two formats are accepted, detected from
                   the styles used (see FORMATS below).
  --project-dir    the HyperFrames caption project in this repo
                   (echoes-hyperframes/, ported 2026-11-09 from the
                   local project): index.html template, vendored GSAP
                   + fonts, tools/build_captions.py (legacy),
                   tools/build_captions_hormozi.py (Hormozi) and
                   tools/render_captions_24fps.sh.
  --out            captions-24fps.mp4 (1080x1920, 24 fps). For the
                   Hormozi format a second file is written next to
                   it: captions-plates-24fps.mp4 (the dark-plate
                   layer, white background, multiply-blended).

FORMATS
  LEGACY (videos 45-55, 65-100 batch): each caption
                   {"start": 0.0, "end": 3.1, "text": "Three to five words",
                    "keyword": "five", "style": "standard",
                    "word_starts": [0.0, 0.4, 0.9, 1.5],
                    "size_px": 70, "bottom_px": 670, "break_after": 2}
                   Styles: punch, standard, list, split, question,
                   quick. 3-5 words, Archivo Black, 60-90px,
                   bottom 670-850 (lower third), keyword gold #FFD166.
  HORMOZI (56 rebuild onwards — the CURRENT style; 62's GitHub
                   render failed on 2026-11-16 because this wrapper
                   only knew the legacy styles): each group
                   {"start": 0.0, "end": 1.68, "text": "PLAY JAZZ OR GET THE",
                    "style": "hook", "size_px": 105, "bottom_px": 1000,
                    "word_starts": [0.0, 0.52, 0.86, 1.3, 1.48]}
                   Styles: hook, body. 1-6 words, ALL-CAPS, Anton,
                   90-150px (hook 105, hook word 125, body 95),
                   bottom 950-1050 (centre), word_starts REQUIRED,
                   active word vivid yellow #FFE600 with a scale snap,
                   per-word dark plates. The builder merges groups
                   under 0.20s/word (readability) and chunks the
                   yellow highlight on fast bursts — same as the local
                   build, so the render matches the approved captioned
                   v1 built locally from the same file.

PLATES (Hormozi only): the builder renders TWO layers. The text
layer (black background, screen-blended over footage) is --out.
The plate layer (white background, dark plates only) is written
next to it as captions-plates-24fps.mp4 and rides the same
`captions` artifact (the workflow uploads the whole out/ dir), so
it is present in the assemble job. The assemble step does NOT yet
consume it — it composites only the text layer with a screen blend,
and a dark plate is invisible in a screen blend (screen can only
lighten). Until the assemble follow-up lands (multiply-blend the
plate layer onto the footage before screening the text layer), a
GitHub final has Hormozi text but NO dark plates. See
echoes-hyperframes/README.md for the exact follow-up patch.

What this script DOES do today: validate the caption JSON against
the Echoes rules for its format, so a bad caption file fails here
instead of in the render.
"""
import argparse
import json
import os
import subprocess
import sys

EM_DASH = "\u2014"
LEGACY_STYLES = ("punch", "standard", "list", "split", "question", "quick")
HORMOZI_STYLES = ("hook", "body")


def fail(msg):
    raise SystemExit(f"echoes_captions: ERROR: {msg}")


def detect_format(captions):
    """'hormozi' if any group uses a Hormozi style, else 'legacy'.

    A file mixing Hormozi and legacy styles fails loudly — the two
    formats have different rules and different builders.
    """
    styles = {c.get("style", "standard") for c in captions}
    if styles & set(HORMOZI_STYLES):
        if styles - set(HORMOZI_STYLES):
            fail(f"mixed caption formats: styles {sorted(styles)} "
                 f"mix Hormozi {HORMOZI_STYLES} with legacy styles")
        return "hormozi"
    return "legacy"


def validate_legacy(captions):
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
        if cap.get("style", "standard") not in LEGACY_STYLES:
            fail(f"caption {i}: unknown style {cap.get('style')!r}")
        size = float(cap.get("size_px", 70))
        if not 60 <= size <= 90:
            fail(f"caption {i}: size_px {size} outside 60-90")
        bottom = float(cap.get("bottom_px", 670))
        if not 670 <= bottom <= 850:
            fail(f"caption {i}: bottom_px {bottom} outside 670-850 (safe band)")
        prev_end = end
    print(f"validated {len(captions)} captions (legacy), "
          f"total {max(float(c['end']) for c in captions):.2f}s")


def validate_hormozi(captions):
    """Mirror tools/build_captions_hormozi.py's validation exactly,
    so the wrapper and the builder agree and a file the wrapper
    passes is one the builder accepts."""
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
        if cap.get("style", "body") not in HORMOZI_STYLES:
            fail(f"caption {i}: unknown style {cap.get('style')!r}")
        size = float(cap.get("size_px", 110))
        if not 90 <= size <= 150:
            fail(f"caption {i}: size_px {size} outside 90-150")
        bottom = float(cap.get("bottom_px", 1000))
        if not 950 <= bottom <= 1050:
            fail(f"caption {i}: bottom_px {bottom} outside 950-1050 (centre)")
        prev_end = end
    n_hook = sum(1 for c in captions if c.get("style") == "hook")
    print(f"validated {len(captions)} captions (hormozi, "
          f"{n_hook} hook, {len(captions) - n_hook} body), "
          f"total {max(float(c['end']) for c in captions):.2f}s")


# Backwards-compatible alias: the old entry point was validate().
validate = validate_legacy


def render_layer(build_script, captions_json, project_dir, variant_args):
    """Build one composition variant and render it at 24 fps.

    Returns the rendered mp4 path (project renders/captions-24fps.mp4).
    variant_args is [] for the text layer, ["plate"] for the plate layer.
    """
    composition = os.path.join(project_dir, "index.html")
    subprocess.run(
        ["python3", build_script, captions_json, composition] + variant_args,
        check=True)
    render_script = os.path.join(project_dir, "tools", "render_captions_24fps.sh")
    subprocess.run(["bash", render_script], check=True, cwd=project_dir)
    rendered = os.path.join(project_dir, "renders", "captions-24fps.mp4")
    if not os.path.exists(rendered):
        fail(f"render produced no {rendered}")
    return rendered


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
    fmt = detect_format(captions)
    if fmt == "hormozi":
        validate_hormozi(captions)
    else:
        validate_legacy(captions)

    # Absolute paths: the render step runs with cwd=project_dir, so a
    # relative script path would be resolved inside the project dir
    # and not found (caught by the local 79 test, 2026-11-09).
    project_dir = os.path.abspath(args.project_dir)
    render = os.path.join(project_dir, "tools", "render_captions_24fps.sh")
    if fmt == "hormozi":
        build = os.path.join(project_dir, "tools", "build_captions_hormozi.py")
    else:
        build = os.path.join(project_dir, "tools", "build_captions.py")
    if not (os.path.exists(build) and os.path.exists(render)):
        fail(
            "HyperFrames caption project missing: "
            f"{os.path.basename(build)} or "
            "tools/render_captions_24fps.sh not found under "
            f"{args.project_dir!r}. Captions JSON validated OK; "
            "nothing was rendered."
        )
    # Ported project present: build the composition, render at 24 fps.
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    if fmt == "legacy":
        rendered = render_layer(build, args.captions_json, project_dir, [])
        os.replace(rendered, args.out)
        print(f"wrote {args.out}")
        return 0
    # Hormozi: two layers. The text layer is --out (the interface
    # stays stable); the plate layer goes next to it and rides the
    # same captions artifact to the assemble job (see module docstring).
    rendered = render_layer(build, args.captions_json, project_dir, [])
    os.replace(rendered, args.out)
    print(f"wrote {args.out} (hormozi text layer)")
    plate_out = os.path.join(
        os.path.dirname(os.path.abspath(args.out)),
        "captions-plates-24fps.mp4")
    rendered = render_layer(build, args.captions_json, project_dir, ["plate"])
    os.replace(rendered, plate_out)
    print(f"wrote {plate_out} (hormozi plate layer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
