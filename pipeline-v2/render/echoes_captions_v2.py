#!/usr/bin/env python3
"""Render Echoes caption karaoke at 24 fps (HyperFrames wrapper), v2.

Live on GitHub (SaNtOsH6099/quiet-ledger, main) — the v2 workflow has
run 54 times, including 79 and 80 v2. Derived from pipeline/render/
echoes_captions.py (v1) on 2026-11-18. v2 changes (audit gaps in
AUDIT.md):
  G2 pause audit + check 6: the v1 builder has neither. v2 uses the
     SYNCED local builder (echoes-hyperframes-v2/tools/
     build_captions_hormozi.py — byte-identical to the local builder,
     with lesson-41 TEST 1/2/2b behind --mix and lesson-43 check 6).
     The workflow passes the locked narration mix with --mix, so a
     mistimed word fails the build here, not at Gate 3. --mix is
     REQUIRED in v2 for the Hormozi builder: the audit is not
     optional. The validator below also enforces check 6 directly, so
     a duplicate-start file fails before the builder runs.
  G2b GEAR extension: RMS-settling EVERY disputed word (>0.15s
     base/small disagreement) is still a LOCAL per-video step — the
     GitHub job receives only captions.json, never the Whisper
     outputs, so it cannot enforce it. The staging contract (see
     README.md) requires the staged captions.json to be the
     RMS-settled one. The pause audit + check 6 catch the silence
     and duplicate classes; the mid-phrase disagreement class
     depends on the local step having been done.
  Legacy guards (2026-11-24, caption tooling build): validate_legacy
     now enforces the same token-level rules as the legacy builder
     (caption_checks.py, shared with both builders and the grouping
     helper) — lesson-88 (0.13s floor / 0.17s bar, with the
     documented-exception mechanism), 0.8s floor for non-hook groups,
     G0 first word at 0.00, keyword cap (max 4, target 3), width
     assert (Archivo Black, 810px box, max 2 lines), 2-6 words sized
     by rendered width (rule 62, fit-based). The legacy builder does
     NOT take --mix (it takes exactly 3 argv); the wrapper no longer
     passes it for legacy. Date cards and hook text are injected into
     the legacy composition too (the injectors are format-agnostic
     since 2026-11-24) — the old Hormozi-only rejection is lifted
     because 81+ videos use date cards and hook text under the new
     method (frame-0 text is mandatory; time jumps take date cards).

Inputs:
  --captions-json  captions.json: a list of caption groups measured
                   from the LOCKED narration (faster-whisper base +
                   small, compared word-for-word, disagreements
                   flagged). Two formats are accepted, detected from
                   the styles used (see FORMATS below).
  --project-dir    the HyperFrames caption project in this repo
                   (echoes-hyperframes-v2/, synced from the local
                   project 2026-11-18): index.html template, vendored GSAP
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
                   quick. 2-6 words, sized by rendered width (rule 62:
                   fill the 810px box, target ~4 words, fewer for long
                   words, more for short ones — never a fixed word
                   count), Archivo Black, 60-90px, bottom 670-850
                   (lower third), keyword gold #FFD166, at most 4
                   groups with a keyword (target 3). First word at
                   0.00s on frame 0; every word >= 0.17s before its
                   group end (lesson 88); groups >= 0.8s (hook exempt).
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

PLATES: the builder renders TWO layers (Hormozi: per-word plates;
legacy: date-card plates only, since the 68 Gate 4 F1 fix 2026-11-25 —
the legacy plate variant carries no caption text, so the multiply
darkens the footage only behind the cards). The text
layer (black background, screen-blended over footage) is --out.
The plate layer (white background, dark plates only) is written
next to it as captions-plates-24fps.mp4 and rides the same
`captions` artifact (the workflow uploads the whole out/ dir), so
it is present in the assemble job. The assemble step does NOT yet
consume it — it composites only the text layer with a screen blend,
and a dark plate is invisible in a screen blend (screen can only
lighten). The v2 assemble step DOES consume the plate layer
(multiply-blend onto the footage before screening the text layer) —
the follow-up this paragraph once waited for has landed; the v1
README's note to the contrary is stale.

DATE CARDS (optional): a Director-plan date card is a
top-centre title card on a time jump (Anton 64px, top 180px, 3.0s).
In the text layer the card is white text with the heavy black
stroke; in the plate layer the card is transparent text on a dark
plate bar (rgba(0,0,0,0.72)), so the multiply darkens the footage
there.
The captions.json schema has no date-card entry, so the cards are
staged separately as date_cards.json (optional; absent = no cards)
and injected into BOTH caption layers by pipeline-v2/render/
date_cards.py, after the builder writes the composition and before
the render runs. The injection is the Gate-3-proven local injector,
generalised: depth-counted insertion (caption divs contain nested
line divs — the naive first-</div> insertion nests the cards inside
the last caption and they never appear) plus verification asserts.
Without this step a GitHub render silently drops the cards, which
are a locked Gate 3 element — that is what 69 found at Gate 4.

HOOK TEXT (optional): the Director-plan hook text is
the approved on-screen text on the opening shot (Director plan §6):
a second fact, not duplicating the spoken line, gold #FFD166, in the
lower-third safe zone for the full shot (e.g. 63: "NO ONE EVER CAME
FORWARD", 0.0-8.7s). The captions.json schema has no hook-text entry,
so it is staged separately as hook_text.json (optional; absent = no
hook text) and injected into the text caption layer (and into BOTH
layers for Hormozi — transparent text + plate bar in the plate layer)
by pipeline-v2/render/hook_text.py, after the builder writes the
composition and before the render runs — the same class as the date
cards, same depth-counted insertion + verification asserts. Without
this step a GitHub render silently drops the hook text, which is a
locked Gate 0 element — that is what 63 found at Gate 4 (the text
lived only in plan/report prose, with no renderable input, so no S1
frame showed it).

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


def validate_legacy(captions, tools_dir, font_path):
    """Validate a legacy captions file against the same token-level
    rules the legacy builder enforces (caption_checks.py, shared with
    both builders and the grouping helper), plus the legacy
    style/size/bottom ranges. `tools_dir` is the project's tools/
    directory (where caption_checks.py lives); `font_path` is the
    Archivo Black TTF the width assert measures with. A valid
    documented lesson-88 exception prints a WARNING but passes."""
    if not isinstance(captions, list) or not captions:
        fail("captions file must be a non-empty JSON list")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import caption_checks as cc
    except ImportError as e:
        fail(f"caption_checks.py is required ({tools_dir}): {e}")
    if not os.path.exists(font_path):
        fail(f"Archivo Black font missing: {font_path} — the width "
             f"assert cannot be proven without the renderer's font")
    violations, warnings = cc.validate_captions(captions, font_path)
    for w in warnings:
        print(f"echoes_captions: WARNING: {w}")
    if violations:
        fail("legacy caption validation failed:\n  " + "\n  ".join(violations))
    # Legacy style/size/bottom ranges (the builder's own geometry).
    for i, cap in enumerate(captions):
        if cap.get("style", "standard") not in LEGACY_STYLES:
            fail(f"caption {i}: unknown style {cap.get('style')!r}")
        size = float(cap.get("size_px", 70))
        if not 60 <= size <= 90:
            fail(f"caption {i}: size_px {size} outside 60-90")
        bottom = float(cap.get("bottom_px", 670))
        if not 670 <= bottom <= 850:
            fail(f"caption {i}: bottom_px {bottom} outside 670-850 (safe band)")
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
    # LESSON 43 (check 6, Gate 3 FAIL #1 video 68): consecutive word
    # starts must fall in different 24fps frames, or the renderer
    # lights same-frame words yellow together. The builder enforces
    # this too; checking here fails the file before the render runs.
    prev = None
    for i, cap in enumerate(captions):
        for j, st in enumerate(cap["word_starts"]):
            st = float(st)
            if prev is not None and int(prev[1] * 24) >= int(st * 24):
                fail(f"caption {i}: lesson 43: {prev[0]!r} {prev[1]:.2f} "
                     f"and {cap['text'].split()[j]!r} {st:.2f} pop on the "
                     f"same frame (frame {int(st * 24)}) — settle the onset")
            prev = (cap["text"].split()[j], st)
    n_hook = sum(1 for c in captions if c.get("style") == "hook")
    print(f"validated {len(captions)} captions (hormozi, "
          f"{n_hook} hook, {len(captions) - n_hook} body), "
          f"total {max(float(c['end']) for c in captions):.2f}s")


# Backwards-compatible alias: the old entry point was validate().
validate = validate_legacy


def render_layer(build_script, captions_json, project_dir, variant_args,
                 mix=None, date_cards_path=None, hook_text_path=None):
    """Build one composition variant and render it at 24 fps.

    Returns the rendered mp4 path (project renders/captions-24fps.mp4).
    variant_args is [] for the text layer, ["plate"] for the plate layer.
    When date_cards_path is given, the date cards are injected into the
    generated composition (both variants) before the render runs.
    When hook_text_path is given, the hook text is injected the same
    way (both variants).
    """
    composition = os.path.join(project_dir, "index.html")
    cmd = ["python3", build_script, captions_json, composition] + variant_args
    if mix is not None:
        cmd += ["--mix", mix]
    subprocess.run(cmd, check=True)
    if date_cards_path is not None:
        try:
            from . import date_cards
        except ImportError:  # run as a plain script, not -m
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import date_cards
        cards = date_cards.load(date_cards_path)
        with open(composition, encoding="utf-8") as f:
            html = f.read()
        html = date_cards.inject(html, cards)
        with open(composition, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"injected {len(cards)} date cards into {composition}")
    if hook_text_path is not None:
        try:
            from . import hook_text
        except ImportError:  # run as a plain script, not -m
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import hook_text
        hook = hook_text.load(hook_text_path)
        with open(composition, encoding="utf-8") as f:
            html = f.read()
        html = hook_text.inject(html, hook)
        with open(composition, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"injected hook text {hook[0]!r} into {composition}")
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
    parser.add_argument("--mix", required=False, default=None,
                        help="locked narration mix wav: REQUIRED in v2 "
                             "for the Hormozi builder (lesson-41 pause "
                             "audit runs on it); the legacy builder does "
                             "not take it (exactly 3 argv), so the wrapper "
                             "does not pass it for legacy")
    parser.add_argument("--date-cards", required=False, default=None,
                        help="date_cards.json (optional): Director-plan "
                             "date cards injected into the caption layers "
                             "before the render; absent = no cards")
    parser.add_argument("--hook-text", required=False, default=None,
                        help="hook_text.json (optional): Director-plan "
                             "hook text injected into the caption layers "
                             "before the render; absent = no hook text")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    # Absolute paths first: the render step runs with cwd=project_dir,
    # so a relative script path would be resolved inside the project
    # dir and not found (caught by the local 79 test, 2026-11-09).
    # Validation needs them too (the shared checks live in the
    # project's tools/ dir, and the width assert needs its font).
    project_dir = os.path.abspath(args.project_dir)
    tools_dir = os.path.join(project_dir, "tools")
    font_path = os.path.join(
        project_dir, "assets", "fonts", "ArchivoBlack-Regular.ttf")

    with open(args.captions_json) as f:
        captions = json.load(f)
    fmt = detect_format(captions)
    if fmt == "hormozi":
        validate_hormozi(captions)
    else:
        validate_legacy(captions, tools_dir, font_path)

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
    # v2: for Hormozi the pause audit is NOT optional. The mix is in
    # the inputs artifact (intake always fetches a narration wav); a
    # missing mix fails here rather than letting a mistimed word reach
    # the renderer. The legacy builder takes exactly 3 argv and runs
    # no audio audit, so --mix is Hormozi-only: it is required for
    # Hormozi and simply not passed for legacy.
    if fmt == "hormozi":
        if args.mix is None:
            fail("--mix is required in v2 for Hormozi (lesson-41 pause audit)")
        if not os.path.exists(args.mix):
            fail(f"--mix file not found: {args.mix}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    if fmt == "legacy":
        # Two layers (68 Gate 4 F1, 2026-11-25): the text layer plus a
        # PLATE layer carrying ONLY the date-card plates. The legacy
        # builder's plate variant renders a white page with invisible
        # caption text, so the multiply darkens the footage behind the
        # cards and nowhere else (a plateless white card over bright
        # sky is unreadable, and a screen blend cannot darken — the
        # 68 v1 defect). Hook text is NOT injected into the plate
        # layer: it sits over dark footage and needs no plate, and the
        # fix is scoped to date cards. Date cards and hook text are
        # injected into the text composition by the same injectors
        # (format-agnostic since 2026-11-24); --mix is not passed —
        # the legacy builder rejects extra argv.
        rendered = render_layer(build, args.captions_json, project_dir, [],
                                mix=None, date_cards_path=args.date_cards,
                                hook_text_path=args.hook_text)
        os.replace(rendered, args.out)
        print(f"wrote {args.out} (legacy text layer)")
        plate_out = os.path.join(
            os.path.dirname(os.path.abspath(args.out)),
            "captions-plates-24fps.mp4")
        rendered = render_layer(build, args.captions_json, project_dir, ["plate"],
                                mix=None, date_cards_path=args.date_cards,
                                hook_text_path=None)
        os.replace(rendered, plate_out)
        print(f"wrote {plate_out} (legacy plate layer)")
        return 0
    # Hormozi: two layers. The text layer is --out (the interface
    # stays stable); the plate layer goes next to it and rides the
    # same captions artifact to the assemble job (see module docstring).
    rendered = render_layer(build, args.captions_json, project_dir, [],
                            mix=args.mix, date_cards_path=args.date_cards,
                            hook_text_path=args.hook_text)
    os.replace(rendered, args.out)
    print(f"wrote {args.out} (hormozi text layer)")
    plate_out = os.path.join(
        os.path.dirname(os.path.abspath(args.out)),
        "captions-plates-24fps.mp4")
    rendered = render_layer(build, args.captions_json, project_dir, ["plate"],
                            mix=args.mix, date_cards_path=args.date_cards,
                            hook_text_path=args.hook_text)
    os.replace(rendered, plate_out)
    print(f"wrote {plate_out} (hormozi plate layer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
