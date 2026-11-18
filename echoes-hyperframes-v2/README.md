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

## Hormozi style (current — 56 rebuild onwards)

The legacy preset above is kept for old-format files. Every video
from the 56 rebuild on uses the Hormozi kinetic style instead:

- `tools/build_captions_hormozi.py` — ported verbatim from the local
  project. Styles `hook` / `body`, 1-6 words per group, ALL-CAPS,
  Anton, 90-150px (hook 105, hook word 125, body 95), bottom
  950-1050 (centre, 50px clear each side). Active word vivid yellow
  #FFE600 with a scale snap to 1.08, inactive words white, per-word
  dark plates (rgba(0,0,0,0.72)). The builder merges groups under
  0.20s/word, chunks the yellow highlight on fast bursts, and uses
  show-all mode for fast body phrases — see its header for the full
  spec. `assets/fonts/Anton-Regular.ttf` is vendored alongside
  Archivo Black.
- Two layers: `pipeline/render/echoes_captions.py` renders the text
  layer to `out/captions-24fps.mp4` (black background, screen blend)
  AND the plate layer to `out/captions-plates-24fps.mp4` (white
  background, plates only). Both ride the `captions` artifact (the
  workflow uploads the whole `out/` dir).
- PLATE FOLLOW-UP (still open): the assemble step composites only
  the text layer with a screen blend, and a dark plate is invisible
  in a screen blend, so a GitHub final currently has Hormozi text
  but NO dark plates. To finish it, `pipeline/render/echoes_assemble.py`
  needs a `--captions-plates` input, composited with a multiply blend
  onto the footage BEFORE the text layer is screened on top:
  `[v0][plate2]blend=all_mode=multiply[vm];[vm][cap2]blend=all_mode=screen`,
  with the plate video tpad-padded to the tailed length exactly like
  the text layer, and the workflow's assemble step needs
  `--captions-plates out/captions-plates-24fps.mp4` passed alongside
  `--captions`. Until that lands, do NOT claim a GitHub final has
  plates — check the composite frames.

## How it is used

`pipeline/render/echoes_captions.py` calls the two scripts above:
build the composition from `captions.json`, then render it. It is
invoked by the `captions` job of `.github/workflows/echoes-render.yml`.
Do not edit `index.html` by hand — it is generated per video and
overwritten on every build.
