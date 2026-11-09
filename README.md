# quiet-ledger — the Echoes Originals render machine

`quiet-ledger` is the hub for Echoes Originals Shorts. The name is
deliberately unsearchable. It is a **staging hub, not the final
destination**.

## The flow

1. **A per-video side chat does the full setup locally** — story research,
   script, narration (Gemini Kore, one continuous take), captions measured
   from that narration, AI clips, per-clip QC. No step is done in GitHub.
2. When the clips are locked, the chat puts the messy assets in the
   video's staging folder in the quiet-ledger Drive folder:
   locked clips, narration mix, `captions.json`, `segment_map.json`,
   the narration-timestamps file.
3. **The Hub dispatches the `echoes-render` workflow** (manual dispatch,
   with video id, staging folder id, title, final filename).
4. GitHub Actions renders only: intake, HyperFrames karaoke captions at
   24 fps, trim-only assembly, cinema finish with two-pass loudnorm at
   -23 LUFS, 1080x1920, 24 fps, no size cap. It returns the final to the
   **same staging folder**.
5. **The Hub does local frame QA** on the returned final, then transfers
   the final video + its narration-timestamps file to their proper place
   in Echoes Drop (for batch 57-100: Echoes Drop / Batch 57-100 /
   `"<id> <topic>"`), and **cleans the staging folder** — the messy
   assets are removed once the video is complete and transferred.

## What this repo is NOT

- No narration in Actions. No Gemini key, no Kokoro.
- No code-drawn scenes, no GSAP scenes, no thumbnail, no `.ass`.
- No clips, narration, scripts or timestamps in the repo. Inputs travel
  via Drive only. The repo is public, so never push video assets to it.
- No QA in Actions. A render can complete cleanly and still have a wrong
  visual at a beat; QA is local, by the Hub, frame by frame in motion.

## The Drive hub

- Drive folder `quiet-ledger` — the staging hub. One folder per video,
  cleaned after the video is complete and transferred to Echoes Drop.
- `svg assets/` inside it — the old SVG asset pack, kept from the
  failed autonomous-shorts experiment. Echoes does not use it.
- The old experiment (code-drawn scenes, Kokoro, Eiffel Tower renders)
  was cleaned out on 2026-11-09. Its only copies are archived at
  `~/workspace/quiet-ledger-archive-2026-11-09/` (local) and in Drive
  trash (recoverable).

## Secrets needed (Actions)

- `DRIVE_OAUTH_JSON` — Google OAuth client + refresh token, as one JSON
  secret. This is the working auth.
- `DRIVE_FOLDER_ID` — the quiet-ledger Drive folder id.

`DRIVE_SERVICE_ACCOUNT_JSON` is **not** used: a service account has no
storage quota and cannot create files in a personal Drive folder.

## How to dispatch a render

GitHub → Actions → `echoes-render` → Run workflow, with:
`video_id` (e.g. `79`), `drive_folder_id` (the staging folder id),
`video_title`, `final_name` (e.g. `79-antikythera-mechanism-v1`).

Then: wait for the run, take the final from the staging folder, do local
frame QA, transfer to Echoes Drop, clean the staging folder.

## Docs

- `PIPELINE.md` — the render pipeline, step by step.
- `docs/ECHOES.md` — the full blueprint: who does what, the staging →
  transfer → clean flow, open decisions, and what is still a placeholder.
