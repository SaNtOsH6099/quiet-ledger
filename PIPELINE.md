# Echoes render pipeline

One workflow: `.github/workflows/echoes-render.yml`, manual dispatch
only. No schedule, no repo submission. Concurrency group
`echoes-render`.

## Inputs (from the staging folder, via `pipeline/drive/echoes_intake.py`)

The per-video staging folder in the quiet-ledger Drive hub holds:
- `clips/` — locked AI clips, one mp4 per segment, 24 fps
- `narration_mix.wav` — Gemini Kore, one continuous take
- `captions.json` — captions measured from the locked narration
  (faster-whisper base + small, compared word-for-word)
- `segment_map.json` — `[{"file", "start", "end"}, ...]`, exact trims
- `narration-timestamps_*.md` — the caption plan / timestamps file

## Jobs

1. **intake** — download the locked inputs from Drive (OAuth as the
   user, `DRIVE_OAUTH_JSON` + `DRIVE_FOLDER_ID`). Fail if any required
   file is missing, or if the segment map names a clip that was not
   fetched.
2. **captions** — `pipeline/render/echoes_captions.py` validates the
   captions JSON (3-5 words, no em dashes, first caption at 0.0s, safe
   band bottom 670-850px, gold keyword in the text) and renders the
   HyperFrames karaoke mp4 at 24 fps.
   **PLACEHOLDER:** the HyperFrames caption project
   (`tools/build_captions.py`, `tools/render_captions_24fps.sh`, vendored
   font + GSAP) is not in this repo yet. Until it is ported from the
   local project, this job fails loudly with a clear message. Do not
   invent a caption renderer.
3. **assemble** — `pipeline/render/echoes_assemble.py` (ported from the
   local 24 fps chain, videos 65-78):
   - per segment, blur-fill the (usually landscape) clip to 1080x1920
     (background scale-to-cover + gblur sigma=40 + brightness -0.25,
     foreground centred), trimmed from the clip's start for the segment
     duration, CRF 18, preset medium, 24 fps; a segment longer than its
     10s clip gets a tpad hold of the last frame, never a known lead
   - concat, then GUARD: concat must be >= the narration mix, or
     -shortest would truncate the narration — fail loudly, do not mux
   - mux narration, 0.5s tail (apad + tpad clone)
   - composite the caption mp4 by blend in RGB (`format=gbrp` on both
     inputs, `blend=all_mode=screen` — blending on YUV420p turns
     magenta)
   - measure the composite's loudness (no -v error: the Parsed_loudnorm
     JSON prints at INFO level)
   - cinema finish in the final encode: hqdn3d, eq grade, colorbalance,
     unsharp, vignette, film grain `noise=alls=7`, fade-out last 0.5s
     only (no fade-in), two-pass loudnorm -23 LUFS (TP -2, LRA 11)
     with measured values and `linear=true`, libx264 CRF 15, preset
     slow, 1080x1920, 24 fps, maxrate 20M, faststart
   - verify: 1080x1920, 24 fps, duration within 0.5s, loudness within
     0.5 LUFS of -23. **No size cap** — Echoes finals are 180-310 MB.
4. **return-to-drive** — upload the final mp4 + render report back to
   the **same staging folder** in quiet-ledger, update `meta.json`
   (status `rendered`, final name, run id, final link). It does NOT
   upload to Echoes Drop and does NOT clean the staging folder.

## After the run (Hub steps, not Actions)

1. Local frame QA on the returned final (frames in motion, joins,
   golds, safe band, 0.5s tail).
2. Transfer the final video + narration-timestamps file to Echoes Drop
   (`Echoes Drop / Batch 57-100 / "<id> <topic>"`), new version name,
   Drive size verified against local size.
3. Clean the staging folder in quiet-ledger: remove the messy assets
   (locked clips, narration, timings, intermediates). The final lives
   in Echoes Drop; the staging folder is empty for the next video.

## Kept from the old pipeline

- `pipeline/drive/drive_queue.py`, `video_env.py` — Drive hub: queue
  index, per-video folders, upload/download, meta.
- `pipeline/tools/check_no_shadow.py` — stdlib-shadowing guard, run by
  every job.
- `pipeline/drive/upload_drive.py`, `ingest.py`, `sync_pack.py` — kept
  but **not used by echoes-render**. `ingest.py` is the old
  repo-submission flow; `sync_pack.py` syncs the SVG pack to the Drive
  folder formerly called `assets` (now `svg assets`) and its default
  subdir name is stale. Do not use either for Echoes until they are
  updated or deleted.
