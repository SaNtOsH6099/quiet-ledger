# Echoes render pipeline v2 — DRAFT (not pushed, not tested in Actions)

The modified-pipeline render track. Same shape as v1
(`echoes-render`), separate folder, so v1 stays untouched and switching
is per video at dispatch: dispatch `echoes-render-v2` for a v2 video,
`echoes-render` for a v1 video — or both on the same video for
comparison. Render only: the method (research, script, narration,
stills, clips, reviews, thumbnail) stays local.

## Layout

```
.github/workflows/echoes-render-v2.yml   # copy of v1 workflow, v2 paths
pipeline-v2/render/echoes_assemble_v2.py # v1 assemble + G1/G3/G4/G5 fixes
pipeline-v2/render/echoes_captions_v2.py # v1 captions wrapper + G2 (--mix, check 6)
pipeline-v2/render/__init__.py
echoes-hyperframes-v2/tools/build_captions_hormozi.py  # byte-identical to the LOCAL builder (pause audit + check 6)
echoes-hyperframes-v2/tools/build_captions.py          # legacy builder (identical to local + v1)
echoes-hyperframes-v2/tools/render_captions_24fps.sh  # identical to local + v1
echoes-hyperframes-v2/assets/                          # Anton + Archivo Black fonts, vendored GSAP (copied from v1)
echoes-hyperframes-v2/{hyperframes,meta,package}.json  # project files (copied from v1)
echoes-hyperframes-v2/README.md                       # copied from v1; its "assemble does NOT consume plates" note is STALE (both v1 and v2 assemble consume them)
scripts/dispatch_echoes_render_v2.py                   # dispatch script for the v2 workflow
AUDIT.md   # the full gap list (G1–G5) with file/line citations
README.md  # this file
```

Shared with v1 (not copied): `pipeline/drive/` (intake, Drive hub,
upload) — intake is input handling, not render behaviour — and the
repo Actions secrets (`DRIVE_OAUTH_JSON`, `DRIVE_FOLDER_ID`). The v2
workflow checks out the whole repo, so the shared code is available.

## What v2 changes vs v1 (each traces to AUDIT.md)

| Gap | v1 behaviour | v2 behaviour |
|---|---|---|
| G1 tail freeze | caption layers tpad-padded INSIDE the composite graph (does not take effect; last caption fades out) | layers pre-extended as standalone files (trim at last full-opacity frame + tpad clone, frame counts verified), composite carries no tpad |
| G2 pause audit + check 6 | builder has neither; captions job never receives the mix | synced local builder (TEST 1/2/2b + check 6); `--mix` required; validator enforces check 6 too |
| G2b GEAR extension | not enforceable (no Whisper outputs on GitHub) | staging contract: staged `captions.json` must be the RMS-settled one (local step) |
| G3 still beats | mp4 clips only | still images (`.jpg/.jpeg/.png/.webp`) accepted as segments, looped for the segment duration |
| G4 grade | pre-fix 58 grade (brightness 0.02, vignette PI/5 — too dark) | current local finish (brightness 0.06, vignette PI/7, hqdn3d 4:4:6:6, unsharp 0.6) |
| G5 silent holds | over-long segment silently held; concat shortfall padded up to 1.0s | over-long segment FAILS; shortfall pad capped at 0.05s, fails above |
| Ken Burns | n/a | segment with a `kenburns` key FAILS LOUDLY (see below) |

Unchanged from v1 (verified matching): 24 fps whole chain, gbrp
blending (plates multiply, text screen), vignette on the WHOLE video,
no fade-in, fade-out last 0.5s only, two-pass loudnorm −23 LUFS with
fresh measured values (`target_offset` never carried), no size cap.

## Ken Burns — UNSOLVED, and v2 refuses to fake it

The modified pipeline is stills-dominant: most beats are stills held
4–8s with a slow Ken Burns move (one direction, small move <8–20%,
toward what the line names). The smooth method for that move is
**unsolved**. `ffmpeg zoompan` is banned — it moves the crop window in
integer-pixel steps, so on fine detail (brick, cobbles) it vibrates
instead of gliding (58 Gap1 lesson). A Ken Burns segment in the segment
map (`"kenburns": "slow push-in"`) makes `echoes_assemble_v2.py` fail
loudly rather than bake in a zoompan.

Candidate directions for the smooth method (NOT verified — prototype
and verify numerically + by eye before any real video uses one):
- Render the move in the HyperFrames/GSAP path (the caption project
  already renders GSAP-animated HTML at 24 fps; a still + slow
  scale/translate is the same machinery, with subpixel transforms).
- A Python/OpenCV renderer that resamples each frame with subpixel
  offsets (e.g. `cv2.warpAffine`), verified by per-second
  mean-abs-diff > 0 and by eye (no stepping, no vibration).
- Pre-render the move as a generated clip (the current method) — but
  that spends a generation slot per Ken Burns beat and defeats the
  stills-dominant saving.

Until one of these is worked out and verified, a Ken Burns beat must
arrive as a pre-rendered mp4 (generated clip) or as a plain still beat
(no motion). The v2 renderer enforces that.

## Staging contract (what the side chat puts in the Drive folder)

Same as v1, plus the v2 additions:
- `clips/` — locked mp4 segments AND/OR locked still images
  (`.jpg/.png`) for still beats. Still beats may also arrive as mp4
  segments (the 64 method); raw stills are the v2-native form.
- `narration_mix.wav` — Gemini Kore, one continuous take (required;
  intake already fetches it, and the captions job now needs it for
  the pause audit).
- `captions.json` — Hormozi groups, RMS-settled locally with the
  shared builder + `--mix` (G2b: the staged JSON must be the settled
  one — GitHub cannot re-settle it).
- `segment_map.json` — `[{"file", "start", "end"}, ...]`, timeline
  times; a still beat is `{"file": "S4-beat1.jpg", "start": 24.36,
  "end": 27.10}`; a Ken Burns request is `{"file": ..., "kenburns":
  "..."}` and will FAIL the render until the smooth method exists.
- `narration-timestamps_*.md` — returned with the final, as in v1.

## Smoke test (done locally 2026-11-18 — NOT an Actions run)

In `/tmp/v2test`: a 1s red still + a 1s blue clip + a 2s sine wav,
caption-free render through `echoes_assemble_v2.py`:
- Output 1080x1920, 24 fps, 2.52s (2s + 0.5s tail), loudness
  −23.00 LUFS, verify passed. Frame at 0.5s is red (the still beat),
  frame at 1.5s is blue (the clip). The finish filter in the log
  shows the corrected grade (hqdn3d 4:4:6:6, brightness 0.06,
  vignette PI/7, unsharp 0.6, grain alls=7:allf=t+u).
- Ken Burns guard: a segment map with `"kenburns"` exits 1 with
  "the smooth Ken Burns method is unsolved — do not bake in zoompan",
  no output file.
- Over-long segment: a 5s segment from a 1s clip exits 1 with
  "re-type as a still beat or re-cut; no silent hold", no output file.
- `last_full_opacity_frame()` verified against the real 64 data:
  returns 1852 for the v3 JSON + v3 caption render (local v3 used
  1853, one frame later at ~92% opacity — immaterial).

## Test-render procedure (before v2 takes a real video)

1. Copy this draft into the repo as new paths (do NOT touch v1):
   `.github/workflows/echoes-render-v2.yml`, `pipeline-v2/`,
   `echoes-hyperframes-v2/`, `scripts/dispatch_echoes_render_v2.py`.
   Push to a branch first if the repo policy wants review; the
   workflow only runs on manual dispatch, so merging it cannot
   trigger a render by itself.
2. Verify the repo Actions secrets (`DRIVE_OAUTH_JSON`,
   `DRIVE_FOLDER_ID`) are still valid — the last known good v1 render
   was the video-79 test on 2026-11-09. If they have expired, both
   tracks fail at intake.
3. Stage a completed video's locked inputs (64 is the natural test:
   clips incl. still-beat mp4s, the v3 `captions.json`, a
   `segment_map.json` built from the 64 assembly windows,
   `narration_mix.wav`, timestamps) in a quiet-ledger staging folder.
4. Dispatch `echoes-render-v2` with the video id / folder / title /
   final name. Watch the run; the captions job must print the pause
   audit lines (TEST 1 passed + TEST 2b per candidate) — if it prints
   the "no --mix" warning instead, the dispatch is misconfigured.
5. Hub QA on the returned final, Gate 4-style: tail freeze (last
   caption frozen at full opacity over the moving tail), spot-check
   the RMS-settled words (GEAR 56.44, AND 20.09), per-second luma vs
   the local cinema v1 (every second within ±10 except the fade
   second), loudness −23 LUFS, 24 fps, 1080x1920.
6. Only after the test render passes does v2 take a real video. If
   it fails, fix in the draft and re-test — v1 is untouched throughout.

## Known limits

- GitHub captions run ~2x slower than local; the win is parallelism
  across videos, not speed per job.
- No QA on GitHub, by design. No thumbnail, no narration, no clips.
- The captions job's HyperFrames render downloads
  `hyperframes@0.9.2` via npx at render time (not vendored).
- The v2 builder must be re-synced from the local builder whenever
  the local one changes (it is byte-identical as of 2026-11-18;
  verify with `diff` — see
  `echoes-hyperframes-v2/tools/SYNC.md`).
