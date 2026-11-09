# ECHOES.md — the Echoes Originals blueprint (input, 2026-11-09)

## The idea in one line

quiet-ledger is the **staging hub** for Echoes Originals Shorts. It
holds the messy assets of a video while it is being made. After the
final video is complete, the final is transferred to its proper place
in Echoes Drop, and the staging folder is cleaned.

## Who does what

| Step | Who | Where |
|---|---|---|
| Story research, shot plan, script | Per-video side chat | Local |
| Narration, Gemini Kore, one continuous take | Per-video side chat | Local |
| Captions, measured from the locked narration (faster-whisper base + small, compared word-for-word) | Per-video side chat | Local |
| AI clips, per-clip QC in motion | Per-video side chat | Local |
| Locked clips + narration + captions.json + segment_map.json + narration-timestamps file into the staging folder | Per-video side chat | Drive: quiet-ledger / `"<id> <topic>"` |
| Dispatch `echoes-render` (`scripts/dispatch_echoes_render.py`, or GitHub UI) | Hub | GitHub Actions |
| Intake, captions render, assembly, cinema finish | GitHub Actions | `echoes-render.yml` |
| Final returns to the staging folder | GitHub Actions | Drive: quiet-ledger / `"<id> <topic>"` |
| Local frame QA (frames in motion, joins, golds, safe band, tail) | Hub | Local |
| Transfer final + narration-timestamps to Echoes Drop | Hub | Drive: Echoes Drop / Batch 57-100 / `"<id> <topic>"` |
| Clean the staging folder (remove messy assets) | Hub | Drive: quiet-ledger |
| Video chat shares its full process memory to the Hub; Hub saves it, then deletes that chat | Hub | Hub chat |

## Why staging, then transfer, then clean

- The staging folder is where the messy work lives: 11-15 locked clips,
  narration, caption timings, segment map, intermediates. Echoes Drop
  holds only the approved final + its narration-timestamps file.
- GitHub Actions never touches Echoes Drop. It only reads from and
  returns to the staging folder. That keeps the render machine's Drive
  access narrow and makes a bad render harmless: the final in Echoes
  Drop is only ever written by the Hub, after QA passes.
- Cleaning after transfer keeps the hub small: one video's mess at a
  time, nothing left behind for the next video to trip over.

## Parallelism (the point of this repo)

- When a video's clips are locked and sent for rendering, the Hub
  creates the next video's side chat, which starts its setup and clip
  generation. Roughly one video rendering on GitHub while one generates
  clips locally.
- The 6-clip generation cap is still per round; the side chat reports
  to the Hub and waits for a Hub "continue", and the Hub checks 5
  minutes later whether it arrived and work resumed, resending if not.
- Hub review of finals is still the bottleneck: do not dispatch more
  renders than the Hub can QA and transfer.

## Folder naming — open decision

- quiet-ledger staging folders use the Echoes Drop form:
  `"<id> <topic>"`, e.g. `78 The Betty and Barney Hill Abduction`.
  (The old experiment used `"NNN - slug"`; that form is dead.)
- Echoes Drop finals live at `Echoes Drop / Batch 57-100 /
  "<id> <topic>"`, video + narration-timestamps file only, new version
  name every time, Drive size verified against local size.

## What was done 2026-11-09 (setup completion)

1. **HyperFrames caption project ported.** `echoes-hyperframes/`
   in this repo: `tools/build_captions.py`,
   `tools/render_captions_24fps.sh`, vendored GSAP + Archivo Black,
   `meta.json` / `package.json` / `hyperframes.json`. `echoes_captions.py`
   builds the composition and renders it at 24 fps; the placeholder
   fail is gone. Tested locally on the 79 captions and end-to-end in
   Actions (see the test run in the Hub report for this date).
2. **Stale files resolved.** `pipeline/drive/ingest.py` deleted (old
   repo-submission flow, broken — it imported the deleted
   `pipeline.validate.scene`). `pipeline/drive/sync_pack.py` kept for
   the SVG pack only, default Drive subdir updated to `svg assets`.
   `SETUP-CHECKLIST.md` rewritten for Echoes.
3. **Dispatch script added.** `scripts/dispatch_echoes_render.py`
   dispatches the workflow via the GitHub API (custom.github-pat);
   it handles no secret itself.
4. **End-to-end test.** One completed video (79, re-rendered from
   its locked clips in a test staging folder) was rendered in Actions
   before the live batch was switched over — see the Hub report for
   the test run id and verification numbers.

## What is still open

1. **Secrets.** `DRIVE_OAUTH_JSON` + `DRIVE_FOLDER_ID` were verified
   by the successful end-to-end test dispatch. `DRIVE_SERVICE_ACCOUNT_JSON`
   is not used and should be removed from repo secrets, along with the
   old Groq/Gemini/NVIDIA keys — the PAT cannot list or remove secrets
   (403), so that step needs the user in the GitHub UI.
2. **Repo visibility:** public. That gives the free unlimited standard
   runners (4 vCPU / 16 GB, 20 concurrent jobs). Everything in the
   repo is public, so no clips, narration, scripts or timestamps ever
   go into the repo — Drive only. Private would drop to 2 vCPU / ~7 GB
   and 2,000 free minutes a month.
3. **Live batch not switched over yet.** The test proved the render
   chain; switching the batch (80 onward) to the parallel/GitHub
   flow is a separate user decision.

## What was cleaned out (2026-11-09)

The failed autonomous-shorts experiment: Kokoro narration, code-drawn
scenes (HyperFrames/GSAP), `.ass` captions, 30 fps / CRF 20 / 100 MB
cap assembly, repo submissions, the SVG pack's repo copy, templates,
guardrails, thumbnail and frame-QC code. Kept: the Drive hub code
(`drive_queue.py`, `video_env.py`, `upload_drive.py`),
`check_no_shadow.py`, base + Drive requirements. The experiment's only
copies are archived at `~/workspace/quiet-ledger-archive-2026-11-09/`
(local) and in Drive trash (recoverable): `queue.json`, the 001 Eiffel
folder (orphan) and the 003 Eiffel folder (complete render).
