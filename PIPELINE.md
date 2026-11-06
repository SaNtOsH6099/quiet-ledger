# Pipeline: stages and handoffs

The pipeline turns one idea into a finished video. Each stage reads its
input from a file and writes its output to a file. The handoff between
stages is the file, never shared memory. If a stage fails, the repair
job fixes it and re-triggers the render.

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

## Stages, in order

| # | Stage | Module | Reads | Writes |
|---|-------|--------|-------|--------|
| 1 | Queue | `pipeline.drive.drive_queue` | queue.json in Drive | the next idea (a topic string) |
| 2 | Draft | `pipeline.brain.draft` | a topic | `script.json`: script + beats + format |
| 3 | Codegen | `pipeline.brain.codegen` | `script.json` | `script.json` + `code` (per-beat markup + timeline) |
| 4 | Voice | `pipeline.render.voice` | `script.json` | `narration.wav` |
| 5 | Scenes | `pipeline.render.render` | `script.json` + `narration.wav` | `silent.mp4` + `timings.json` + `words.json` |
| 6 | Captions | `pipeline.render.captions` | `words.json` + `script.json` | `captions.ass` |
| 7 | Assemble | `pipeline.render.assemble` | `silent.mp4` + `narration.wav` + `captions.ass` | `final.mp4` |
| 8 | Frame QC | `pipeline.qc.frame_qc` | `final.mp4` + `script.json` + `timings.json` | `qc-report.json`; fails the render on clipped or missing text |
| 9 | Thumbnail | `pipeline.render.thumbnail` | `script.json` | `thumbnail.png` |
| 10 | Upload | `pipeline.drive.upload_drive` | `final.mp4` + `thumbnail.png` + build files | video's folder + queue entry marked `in-drive` |

## Scene-code freshness: the codegen version

`pipeline.brain.codegen` stamps `codegen_version` (and
`code_provider`) into script.json when it writes the code. Bump
`CODEGEN_VERSION` in codegen.py whenever the prompt, the design
system, or the validation rules change in a way that makes older
scene code unreliable.

Before narrating, the render job runs `codegen --check`: it re-validates
the stored code (same validation the brain's output must pass,
including the CSS check that measures real text widths) and regenerates
it only when it is stale (older version) or invalid. A fresh script
passes through untouched, with no brain calls. The scenes job also
refuses to render stale code (exit 3 = regenerate). This is what stops
a re-render from silently replaying old broken code: entry 3's clipped
hook and missing closing text shipped twice because the render trusted
the stored code blindly, and the new checks never ran on it.

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
- A QC failure is a scene-code defect: the repair job recognises the
  "frame_qc:" error lines and regenerates the code instead of patching
  a repo file. The qc-report.json is filed into the video's folder.

## The brain

`pipeline.brain.providers` is the shared provider rotation. Every brain
call (draft, codegen, repair) goes through `generate()` there, so the
rotation lives in exactly one place.

- Default order (draft, repair): NVIDIA -> Groq -> local. Gemini was
  removed 2026-11-06: 20 requests/day free tier, 503s under demand.
- Codegen order (writing scene code is the most demanding task):
  NVIDIA -> Groq -> local. The NVIDIA leg tries the Nemotron
  550B first (tested 2026-11-06: it replies), then the 30B. Groq is
  LAST in both orders (its free TPM is only 8000, the tightest).
- Keys come from the environment (GitHub Secrets), never from files.
  Groq key 2 of 4 is INVALID (401); 3 working keys remain. Groq free
  TPM is 8000/min, so codegen prompts are kept short.

## Codegen: one beat at a time, with the whole story in context

`pipeline.brain.codegen` writes one beat's scene code per brain call.
The brain gets the FULL script and story in context, plus the previous
and next beat's idea, so the scene fits the flow and the subject stays
the same across beats. But it writes ONLY that one beat's scene. One
beat at a time, with the whole story in mind.

The prompt demands a finished illustration, not a sketch: fill the
frame, build in layers (background, middle, foreground), let the scene
decide how many elements it needs. No minimum numbers: a number is a
limiter, and the brain optimizes for the minimum instead of the scene.

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

## Repair (self-heal)

If a render fails, the repair job runs. It fetches the failed run's
log (`pipeline.repair.fetch_failed_log`, Bearer on the API hop, no auth
on the blob), asks the brain to fix it, and re-triggers the render.

- If the failure is in the scene code, the brain regenerates the
  code for the failing beats (`codegen.py --regen`) and the queue
  entry is reset to approved. Capped at 3 regenerations.
- If the failure is in a repo file, the brain patches the file,
  commits it, and re-triggers. Capped at 3 consecutive repair commits.
- If both caps are hit, the entry is left at `rendering` and a human
  has to look. There is no alert yet; that is an open gap.

## Visual QC

The pipeline's static checks (HyperFrames check, CSS check, word-count
rule) catch layout errors, but they do not catch a scene that renders
and still looks wrong. The human visual QC step belongs in the control
app (Phase 3): the app shows the rendered frames per beat and the user
approves or flags them.

## Config and requirements

- `config/guardrails.json`: the format rules (dynamic, app-editable).
- `config/config.example.json`: an example config.
- `requirements/`: one file per job, each starting with `-r base.txt`
  so a package is listed in exactly one place. `all.txt` is everything,
  for local runs.
