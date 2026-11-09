# Echoes HyperFrames caption project (ported 2026-11-09)

The caption layer for Echoes Originals Shorts, ported verbatim from
the local project `~/workspace/video-tools/echoes-hyperframes/`
(except this README). It renders word-level karaoke captions at
24 fps, 1080x1920, from a captions JSON measured from the locked
narration.

## Files

- `tools/build_captions.py` — builds `index.html` (a self-contained
  HyperFrames composition) from a captions JSON file. Enforces the
  Echoes rules: 3-5 words per caption, no em dashes, first caption
  at 0.0s, keyword must be a word in the text, size 60-90px,
  bottom 670-850px (safe band). GSAP + Archivo Black are vendored
  in `assets/` and embedded, so a render needs no CDN.
- `tools/render_captions_24fps.sh` — renders the composition with
  `npx hyperframes@0.9.2 render . -o renders/captions-24fps.mp4
  --fps 24 --resolution portrait --quality delivery
  --keyframe-interval 2 --low-memory-mode --workers 1`. Takes no
  arguments and always writes the same fixed file; rename it after.
- `assets/gsap.min.js`, `assets/fonts/ArchivoBlack-Regular.ttf` —
  vendored GSAP 3.15.0 and Archivo Black (OFL).
- `meta.json`, `package.json`, `hyperframes.json` — project metadata
  for the HyperFrames CLI.

## The Echoes preset (baked into build_captions.py)

- Caption box: left 90px, width 810px, bottom 670px (bottom of
  captions at y = 1250, clear of the right-side rail and bottom UI).
- Archivo Black, 70px, big bold white with black outline, centred.
- Keyword word in gold (#FFD166) with an extra pop.
- Words pop in one by one, 0.07s apart, 0.28s each, from scale 0.85 /
  y +24 / opacity 0, easing `back.out(1.7)`; hold for the full
  caption duration (minimum 2s); fast 0.12s fade at the end.

## How it is used

`pipeline/render/echoes_captions.py` calls the two scripts above:
build the composition from `captions.json`, then render it. It is
invoked by the `captions` job of `.github/workflows/echoes-render.yml`.
Do not edit `index.html` by hand — it is generated per video and
overwritten on every build.
