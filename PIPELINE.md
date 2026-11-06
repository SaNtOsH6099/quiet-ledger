# Pipeline: stages and handoffs

Muse is the brain and GitHub Actions is the rendering machine. Muse
works outside Actions: topic, script, beats, scene code, validation,
and a demo render with frame QC. The finished script.json is pushed
to the repo under `submissions/<slug>/script.json`. GitHub Actions
does only the computing: ingest the submitted script into Drive,
narrate, draw the scenes, caption, assemble, QC, thumbnail, upload.
No model is called from Actions, and no brain keys are needed. The
only secrets are the Drive OAuth token and the Drive folder id.

Each stage reads its input from a file and writes its output to a
file. The handoff between stages is the file, never shared memory.
If a stage fails, the mark-failed job records it on the queue entry
and in the video's meta.json, and Muse fixes it and submits again.

## One video, one environment

Every video is an entirely separate environment: one Drive folder,
"NNN - slug", that holds EVERYTHING for that video. The folder is the
video; deleting it deletes the video completely.

    NNN - slug/
      script.json         — the script: beats, scene code, codegen
                            version, provider, format.
      meta.json           — status, topic, timestamps, provider,
                            codegen version, drive links.
      narration.wav       — the narration (kept so re-assembly does
                            not need to re-narrate).
      words.json          — word timings for captions.
      captions.ass        — the caption file.
      silent.mp4          — the rendered scenes, no audio.
      NNN - slug.mp4      — the finished video.
      NNN - slug-thumb.png — the thumbnail.

`queue.json` in the Drive root is only a THIN INDEX: one entry per
video with {id, topic, status, folder_id, drive_link}. It points at
the video's folder; it does not hold the script. `pipeline.drive.
video_env` is the only module that touches a video's folder;
`pipeline.drive.drive_queue` only touches queue.json. An old-format
entry (script embedded in queue.json, no folder) is migrated into
its own folder automatically the first time it is rendered.

## How a video is made

Muse's half (outside Actions):

1. Pick a topic with the user, fact-check it, draft the script
   (55-110 words, one continuous narration) and plan the beats
   (one visual idea per beat).
2. Write the scene code for each beat: the HTML/SVG markup and the
   GSAP timeline, invented for that scene, one beat at a time, with
   the full script and the neighbouring beats in mind so the subject
   stays the same across beats. No fixed templates.
3. Validate the code with `pipeline.validate` (structure, big-text
   limits, CSS text widths, JS syntax, hard kill), render a demo
   locally, QC the frames, and show the result to the user.
4. On approval, push the finished script.json to the repo under
   `submissions/<slug>/script.json` and trigger the workflow (or
   leave it for the morning schedule).

GitHub Actions' half (the workflow, one render chain):

| # | Stage | Module | Reads | Writes |
|---|-------|--------|-------|--------|
| 1 | Ingest | `pipeline.drive.ingest` | `submissions/*/script.json` in the repo | script in the video's folder + queue entry `approved` |
| 2 | Voice | `pipeline.render.voice` | `script.json` | `narration.wav` |
| 3 | Scenes | `pipeline.render.render` | `script.json` + `narration.wav` | `silent.mp4` + `timings.json` + `words.json` |
| 4 | Captions | `pipeline.render.captions` | `words.json` + `script.json` | `captions.ass` |
| 5 | Assemble | `pipeline.render.assemble` | `silent.mp4` + `narration.wav` + `captions.ass` | `final.mp4` |
| 6 | Frame QC | `pipeline.qc.frame_qc` | `final.mp4` + `script.json` + `timings.json` | `qc-report.json`; fails the render on clipped or missing text |
| 7 | Thumbnail | `pipeline.render.thumbnail` | `script.json` | `thumbnail.png` |
| 8 | Upload | `pipeline.drive.upload_drive` | `final.mp4` + `thumbnail.png` + build files | video's folder + queue entry marked `in-drive` |

Ingest runs first on every workflow run (manual or scheduled). It
validates each submission before filing it, so a bad script fails the
ingest job and never reaches Drive. A submission whose entry is
already in-drive or rendering is skipped unless a queue_id was given
explicitly: a re-submit must not silently re-queue a finished video.
With no submissions in the repo it exits quietly, so the daily
schedule can run it every morning and only render when there is an
approved entry.

## Scene-code freshness: the codegen version

Muse stamps `codegen_version` (and `code_provider`) into script.json
when the code is written. Bump `CODEGEN_VERSION` in
`pipeline/validate/scene.py` whenever the validation rules or the
design system change in a way that makes older scene code unreliable.

Ingest validates the stored code (same validation the writer's output
must pass, including the CSS check that measures real text widths)
and refuses a stale or invalid script. The scenes job also refuses
to render stale code (exit 3 = the code is stale or invalid; Muse
must fix the script and submit a corrected one). There is no
regeneration in Actions. These checks are what stop a re-render from
silently replaying old broken code: entry 3's clipped hook and
missing closing text shipped twice because the render trusted the
stored code blindly, and the new checks never ran on it.

## Frame QC: check the actual rendered video

`pipeline.qc.frame_qc` runs on the finished video, after assembly and
before upload. The static checks (CSS, validator) run on the code;
this runs on the real frames, so it catches what they cannot see.

- Tier 1 (ffmpeg, zero new deps): blackdetect / freezedetect /
  signalstats in one decode pass — blank frames, frozen segments,
  near-empty frames.
- Tier 2 (RapidOCR): one frame per beat at the hold point (70%
  through the beat, after the text has drawn in). An OCR box touching
  the left or right frame edge is clipped text; a beat whose markup
  has a big-text element but whose frame shows no scene text in the
  scene-text zone (above the caption zone) is missing text. Verified
  2026-11-06 on entry 3's defective render: it catches all three
  defects (hook clipped, "Engineers designe" clipped, closing text
  missing) with no false positives on the clean chart beat.
- A QC failure is a scene-code defect: the render fails, the entry is
  marked failed, and Muse fixes the code and submits a corrected
  script. The qc-report.json is filed into the video's folder.

## Muse writes the code

Muse writes one beat's scene code at a time, with the full script and
story in context, plus the previous and next beat's idea, so the scene
fits the flow and the subject stays the same across beats. But it
writes ONLY that one beat's scene. One beat at a time, with the whole
story in mind.

The code must be a finished illustration, not a sketch: fill the
frame, build in layers (background, middle, foreground), let the scene
decide how many elements it needs. No minimum numbers: a number is a
limiter, and the writer optimizes for the minimum instead of the scene.

The validator (`pipeline.validate.scene`) is the spec the code is
written against: one beat div with the %%ID%% / %%START%% /
%%DURATION%% placeholders, big-text limits per format, CSS-measured
text widths, real JS syntax via node --check, and the exit fade +
hard kill appended mechanically. A beat that fails validation is
fixed before it is submitted, never shipped.

## Guardrails

`pipeline.guardrails` holds the basic rules that keep the video from
breaking. They are different for Shorts and long-form, and they live
in `config/guardrails.json` (data, not code) so the control app can
read and change them later without a code push.

- Shorts: 1080x1920, 30-60s, fast pace, big text max 4 words/24 chars.
- Long-form: 1920x1080, 10-15 min, chapters, slow pace, big text max
  6 words/40 chars.
- Both: core GSAP only, no plugins; prepDraw/dashLen never on text;
  no duration arithmetic from S/E; hard kill appended mechanically;
  everything inside the canvas margins.

`pipeline.guardrails.css_check` measures the actual rendered width of
every text line from the stylesheet and flags any that would run off
the frame. The word-count rule is a proxy; the CSS measurement is the
real check.

## On failure

If a render fails, the mark-failed job runs. It marks the rendering
entry "failed" and records the run id in the video's meta.json, so
the failure is visible instead of the entry sitting at "rendering"
forever with no one knowing. There is no self-healing repair and no
re-trigger: the brain that fixes a failure is Muse, who reads the run
log, fixes the script or the repo, and submits again. A failed entry
can be re-rendered by submitting a corrected script for it (with the
same queue_id).

## Visual QC

The pipeline's static checks (HyperFrames check, CSS check, word-count
rule) catch layout errors, but they do not catch a scene that renders
and still looks wrong. The human visual QC step belongs in the control
app (Phase 3): the app shows the rendered frames per beat and the user
approves or flags them. Until then, Muse QCs the demo frames locally
before submitting, and the finished video is shown in chat before
anything is posted.

## Config and requirements

- `config/guardrails.json`: the format rules (dynamic, app-editable).
- `config/config.example.json`: an example config.
- `requirements/`: one file per job, each starting with `-r base.txt`
  so a package is listed in exactly one place. `all.txt` is everything,
  for local runs.
