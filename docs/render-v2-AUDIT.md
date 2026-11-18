# Audit — Echoes GitHub render pipeline (v1) vs the current local method

Audited 2026-11-18. v1 = `SaNtOsH6099/quiet-ledger` on main: `pipeline/`
+ `echoes-hyperframes/`, workflow `.github/workflows/echoes-render.yml`.
Local method = the 64/65/68 batch (lessons 38–41, 43–45), builder
`~/workspace/video-tools/echoes-hyperframes/tools/build_captions_hormozi.py`,
cinema finish `~/workspace/video-tools/flannan-64-rebuild/work/build_cinema_64_v1.sh`
(68 v2 template), captioned composite
`~/workspace/video-tools/flannan-64-rebuild/work/build_captioned_v3.sh`.

## Verdict up front

**v1 as-is must NOT take a render today.** It would produce a file, but
the file would carry three defects that failed Gates on 64/65/68: the
tail freeze (G1), un-audited caption timing (G2), and the too-dark
pre-fix grade (G4). v1 last proved itself on the end-to-end test render
of video 79 on 2026-11-09 — before lessons 41/43, before the tail-freeze
fix, and before the 58 grade fix. It has not been re-verified against
the current method since. The v2 draft in this folder closes G1–G5;
it needs a test render (see README.md) before it takes a real video.

## G1 — Tail freeze: caption layers tpad-padded INSIDE the composite graph (CRITICAL)

- **v1 code:** `pipeline/render/echoes_assemble.py`, composite section —
  `[1:v]tpad=stop_duration={...}:stop_mode=clone,fps=24[cap]` and the
  same for the plate layer, inside the `-filter_complex` of the
  composite ffmpeg call.
- **Why it fails:** 64 Gate 3 FAIL #1 (2026-11-18 01:17 IST) — the last
  caption faded out completely over the last 0.46s. Root cause, proven
  by the producer's isolation test: `trim`+`tpad` inside the composite
  filter graph does NOT take effect. The working mechanism (64 v2):
  pre-extend the text+plate layers as standalone files (trim at the
  last full-opacity frame + tpad clone), verify the frame counts, then
  composite with NO trim/tpad in the graph —
  `~/workspace/video-tools/flannan-64-rebuild/work/build_captioned_v3.sh`
  lines 24–26 (method comment), 38–41 (pre-extension), 51 (composite
  with no tpad).
- **Second half of the same defect:** the caption video's last frame is
  already faded. Both builders fade the last group out over
  `exit_dur = min(0.12, (end - start) * 0.3)` at its end
  (`echoes-hyperframes/tools/build_captions_hormozi.py`, exit-fade
  block). So even if the in-graph tpad worked, it would clone a faded
  frame and freeze a faded caption.
- **Consequence:** any v1 final fails the Gate 4 tail check (last
  caption must stay frozen at full opacity over the moving tail).
- **v2 fix:** `pipeline-v2/render/echoes_assemble_v2.py` —
  `last_full_opacity_frame()` computes the last fully-opaque frame from
  the captions JSON (group end − exit_dur, frame whose end is at/before
  the fade start), pre-extends both layers as standalone files, verifies
  the frame counts, composites with no tpad. Verified against the real
  64 data: last full-opacity frame 1852 (local v3 used 1853, one frame
  later at ~92% opacity — immaterial, red-team verified frozen).

## G2 — No pause audit (lesson 41) and no check 6 (lesson 43) in the captions path (CRITICAL)

- **Drift:** the GitHub Hormozi builder
  (`echoes-hyperframes/tools/build_captions_hormozi.py`) was last
  committed 2026-11-17T07:52:42Z (`1a0720a8`, show-all mode). The local
  builder has **202 more lines**: `pause_audit()` (TEST 1 / TEST 2 /
  TEST 2b) behind `--mix`, and the lesson-43 check 6 (consecutive word
  starts must fall in different 24fps frames). Diff verified
  2026-11-18.
- **The wrapper does not cover it either:** `pipeline/render/echoes_captions.py`
  `validate_hormozi()` checks structure only (1–6 words, ALL-CAPS,
  word_starts present, size 90–150, bottom 950–1050, first at 0.0, no
  em dash). No timing audit of any kind.
- **The workflow does not feed it:** the captions job passes only
  `--captions-json in/captions.json`. The narration mix IS in the
  inputs artifact (intake always fetches a narration wav as
  `in/narration_mix.wav`) but is never passed to the captions job.
- **Consequence:** a JSON with a word starting inside a ≥0.4s silence
  (65: AND 60.60 lit during a full second of silence; 64: AND 19.68
  0.41s early) or duplicate starts (68: AND/HER sharing 55.82) passes
  GitHub validation and renders wrong captions — the exact defects
  that failed Gate 3 on 64/65/68.
- **v2 fix:** `echoes-hyperframes-v2/tools/build_captions_hormozi.py`
  is byte-identical to the local builder (verified by diff), the
  workflow passes `--mix in/narration_mix.wav`, and
  `pipeline-v2/render/echoes_captions_v2.py` requires `--mix` and
  enforces check 6 in the validator too. No requirements change:
  `numpy==2.5.4` is already in `requirements/base.txt` (shared by
  every job) and ffmpeg is already apt-installed in the captions job.

### G2b — GEAR extension: RMS-settle EVERY disputed word (PROCESS GAP, cannot be fixed in code here)

- Lesson 41's extension (64 Gate 3 FAIL #2, 2026-11-18 02:32 IST):
  every word where base/small Whisper disagree by >0.15s must be
  RMS-settled, including mid-phrase ones (GEAR 56.60 → 56.44, 0.16s
  late, no silence involved). This lives in the per-video build
  scripts locally, not in the shared builder — and the GitHub job
  receives only `captions.json`, never the Whisper outputs, so it
  cannot enforce it.
- **Staging contract (see README.md):** the staged `captions.json`
  must be the RMS-settled one, built locally with the shared builder
  + `--mix`. The pause audit + check 6 catch the silence class and
  the duplicate class; the mid-phrase disagreement class depends on
  the local step having been done.

## G3 — Still beats: no still-image segment type (MODERATE; blocking for the modified pipeline)

- **v1:** intake + assemble expect mp4 clips only (`PIPELINE.md`:
  "`clips/` — locked AI clips, one mp4 per segment"). The assemble
  probes each segment and re-encodes with `-t dur`; a still image
  input yields ~1 frame and the concat comes up short.
- **Current method:** the local side stages still beats as mp4
  segments (64: `clips/64-S4-beat1-kitchen.mp4`,
  `64-S4-beat2-bunks.mp4`, `64-S4-beat3-calendar.mp4`,
  `64-S4-beat4-kitchen.mp4`), so v1 CAN render a current-method video
  if staged that way — but it is undocumented, and the modified
  pipeline is stills-dominant (most segments are stills), so the
  conversion burden explodes.
- **v2 fix:** `echoes_assemble_v2.py` accepts still images
  (`.jpg/.jpeg/.png/.webp`) as segments and loops the still for the
  segment duration. Verified in the smoke test (see README.md).

## G4 — Cinema grade = the pre-fix 58 grade (HIGH — would fail the Gate 4 luma check)

- **v1:** `pipeline/render/echoes_assemble.py`, `video_filter`:
  `hqdn3d=1.5:1.5:6:6`, `eq=contrast=1.10:saturation=1.18:brightness=0.02`,
  `vignette=PI/5`, `unsharp=5:5:0.5:5:5:0.0`.
- **Local current** (`build_cinema_64_v1.sh`, 58 Pass 2 v2):
  `hqdn3d=4:4:6:6`, `brightness=0.06`, `vignette=PI/7`,
  `unsharp=5:5:0.6:5:5:0.0`.
- **Proof it matters:** `build_cinema_pass2_v2.sh` (58) documents the
  red-team fail of exactly the v1 values — grade too dark, mean −18.6
  luma vs the base; brightness 0.02 → 0.06 and vignette PI/5 → PI/7
  were the fix. The vignette angle works backwards from the first
  guess: a LARGER angle is a STRONGER vignette (PI/5 letter 163.8,
  PI/7 183.5). A v1 final would fail Gate 4's per-second luma check
  (every second within ±10 of the base).
- **v2 fix:** grade values corrected in `echoes_assemble_v2.py`.
- **Correction to an earlier reading:** grain DOES match —
  `noise=alls=7:allf=t+u` in both v1 and local (first misread as
  `alls=7` only; verified by grep).

## G5 — Silent holds mask planning defects (MODERATE)

- **v1:** a segment longer than its clip gets a silent `tpad` hold of
  the last frame (logged, not failed); a concat shortfall of up to
  1.0s is silently padded the same way.
- **Local method (NO HOLDS):** an unplanned hold is banned. A fill of
  ≤1s must be ruled as a fill at review (64 S2 tail push, 0.54s);
  anything longer must be re-typed as a still beat. The v1 silent
  hold would pass a defect the local method rejects.
- **v2 fix:** over-long segments FAIL loudly; the shortfall pad is
  capped at 0.05s (frame quantisation, 1/24s = 0.042s) and fails above
  it. Both verified in the smoke test.

## What matches — verified, no gap

- **24 fps whole chain:** captions `--fps 24`, segments `-r 24`,
  finish `-r 24`.
- **gbrp blending:** `format=gbrp` on both inputs, `blend=all_mode=screen`;
  Hormozi plates multiplied first, then text screened on top — matches
  the local v3 composite.
- **Vignette on the WHOLE video:** single filter chain, no split/concat,
  no tail exclusion — matches the 68 v2 lesson (68 v1's +6.2 brightness
  step at the fade start came from excluding the vignette from the tail).
- **No fade-in; fade-out last 0.5s only** (`fade=t=out:st={mix_dur}:d=0.5`).
- **Two-pass loudnorm −23 LUFS, linear=true, measured fresh each run:**
  `measure_loudness()` runs loudnorm WITHOUT `-v error` (the JSON prints
  at INFO level; `-v error` suppresses it) and the apply uses the fresh
  measured values including `target_offset` — never a carried value.
  `target_offset` is unstable run-to-run (1.20/1.04/0.96/1.20/1.20 on
  identical audio), which is why the fresh measurement matters.
- **Legacy builder + render script byte-identical to local**
  (`build_captions.py`, `render_captions_24fps.sh` — diff exit 0).
- **Intake downloads the narration mix** — so `--mix` is available to
  the captions job without any intake change.
- **No size cap** (documented; finals are 180–310 MB).
- **Concat guard** (fail if concat < mix) exists in v1 — weakened by
  the 1.0s silent pad (G5).

## Known limitations (not gaps)

- **GitHub captions job runs ~2x slower than local** (verified
  earlier). The win is parallelism across videos, not speed per job.
- **No QA on GitHub, by design** — Hub does frame QA locally after the
  render returns. No thumbnail, no narration, no clips, by design.
- **The v1 render-report.json records size/duration only**, no
  loudness (the assemble job verifies loudness internally and fails
  if it is >0.5 LUFS off −23).
- **The v1 `echoes-hyperframes/README.md` is stale:** it says the
  assemble step "does NOT yet consume" the plate layer — it does now
  (the workflow passes `--captions-plates` when the file exists). The
  v2 copy carries the same stale note; the v2 README corrects it.

## What was NOT verified

- **No live Actions run was made** (nothing was pushed). The v2 code
  was smoke-tested locally only (see README.md) — the Actions
  environment (ubuntu-latest, ffmpeg from apt, `npx hyperframes@0.9.2`)
  is untested for v2. The captions job's HyperFrames render is the
  least-verified step: it downloads `hyperframes@0.9.2` via npx at
  render time.
- **The v1 workflow's actual run history was not checked** (no runs
  list pulled). The last known good v1 render is the video-79
  end-to-end test on 2026-11-09.
- **Drive secrets state was not checked** (`DRIVE_OAUTH_JSON` /
  `DRIVE_FOLDER_ID` in repo secrets). The v2 workflow reuses the same
  secrets; if they have expired since the 79 test, both tracks fail
  at intake. Verify before the test render.
- **The modified pipeline's Ken Burns method is UNSOLVED** (see
  README.md). The v2 renderer refuses Ken Burns segments loudly
  rather than faking them.
