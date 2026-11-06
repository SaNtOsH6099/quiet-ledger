# quiet-ledger

A small personal system that turns a written idea into a finished
narrated file. Muse writes the words and draws every scene in code;
GitHub Actions is only the rendering machine: it narrates, renders,
captions, assembles, and files the finished file in Drive for review.
Nothing here costs money and nothing needs a card.

Every visual is drawn in code: line drawings, animated charts, stick
figures, diagrams, kinetic text. No photos, no stock, no generated
imagery of any kind.

The pipeline is organized by stage under `pipeline/` (guardrails,
validate, render, drive, qc, tools). Each stage reads its input
from a file and writes its output to a file; the handoff between stages
is the file. See `PIPELINE.md` for the stage list, what each stage
consumes and produces, and the guardrails.

## How one idea becomes a finished file

1. You pick a topic with Muse, who fact-checks it and drafts the
   script (one continuous narration, 55-110 words) and plans the
   scenes (one visual idea per beat).
2. Muse writes the scene code itself: the HTML/SVG markup and the
   animation timeline for each beat, invented for that scene. No fixed
   templates; different scenes get different code because the story is
   different. Muse gets the full script and story in context and
   writes one beat at a time, so each scene fits the flow and the
   subject stays the same across beats.
3. Muse validates the code, renders a demo locally, checks the frames,
   and shows you the result here. You read it and approve it.
4. On your approval, Muse pushes the finished script.json to the repo
   under `submissions/<slug>/script.json` and triggers the workflow
   (or leaves it for the morning schedule).
5. GitHub Actions ingests the submission into the video's Drive folder
   and marks the queue entry approved.
6. Kokoro narrates it in one continuous take.
7. The scene code is rendered into the silent scenes.
8. faster-whisper times every word; captions are built in 3 to 4 word
   chunks, bold white with a black outline, lower third.
9. ffmpeg assembles the finished file: 1080x1920, 30fps, -23 LUFS,
   light grain. A frame QC gate checks the finished video before it
   is filed.
10. A thumbnail is drawn in code.
11. The finished file and thumbnail land in Drive.
12. You watch it in Drive and post it yourself, by hand.

If a render fails, the pipeline marks the entry failed and records the
run in the video's meta.json. There is no self-healing repair: Muse
reads the run log, fixes the script or the repo, and submits again.

## Guardrails

Basic rules so the video does not produce unnecessary bugs. They are
different for Shorts and long-form, because the formats are different
mediums. The rules live in `guardrails.json` (data, not code), so the
control app can read and change them later without a code push. Muse
writes the code against the format's rules, and the validator enforces
them; a beat that breaks a rule is fixed before it is submitted, never
shipped.

- Shorts: vertical 1080x1920, 30 to 60 seconds, fast pace, hook in the
  first seconds. Big text lines hold at most 4 words (24 characters).
- Long-form: horizontal 1920x1080, 10 to 15 minutes, chapters, slow
  pace with breathing room. Big text lines hold at most 6 words
  (40 characters).
- Both: core GSAP only, no plugins; prepDraw/dashLen only on paths,
  never on text; no duration arithmetic from S/E; hard kill appended
  mechanically; everything inside the canvas margins.

Steps 5 to 11 run on GitHub's machines, not yours. Your machine never
renders anything.

## Muse is the brain

Muse writes the script, plans the beats, and writes the scene code,
because the free models that used to do it wrote code that failed
validation and rendered badly (tested 2026-11-06: the best of them
passed 3 of 5 beats clean, the rest 0 of 5). Muse's code passed 5 of 5
and rendered clean, with proper detail and pacing.

The trade-off is stated plainly: the pipeline needs Muse to make a
video. If Muse is not around, GitHub can still render, but nothing
new gets written and nothing broken gets fixed on its own. That sets
aside the old independence goal (the pipeline keeping working without
Muse), which the user set aside on purpose when he made this call.

## Setup

You need three things. Everything below is free and needs no card.
There are no brain keys: no model is called from Actions.

### 1. Google Drive access (OAuth as you)

A service account cannot create files in a personal Drive folder
(it has no storage quota of its own), so the jobs sign in as you
instead, using OAuth. The token is long-lived because the app is
published to Production.

1. Go to console.cloud.google.com and create a project (any name).
2. In that project, open APIs and Services, Library, search for
   Google Drive API, and enable it.
3. Open APIs and Services, OAuth consent screen (now called Google
   Auth Platform). Set User Type to External, app name
   quiet-ledger, your Gmail as support and developer contact. On the
   Branding page, fill in the App domain: home page is this repo's
   URL, privacy policy link is the `PRIVACY.md` file in this repo
   (raw.githubusercontent.com URL). Then publish the app
   (Audience, Publishing status, Publish app). Publishing stops the
   token expiring after 7 days.
4. On the same Auth Platform page, open Clients, Create Client,
   type Web application, name quiet-ledger-web. Under Authorized
   redirect URIs add `https://developers.google.com/oauthplayground`
   and Create. Copy the Client ID and Client Secret.
5. Open developers.google.com/oauthplayground. Tap the gear, tick
   "Use your own OAuth credentials", paste the Client ID and
   Secret, Close. In "Input your own scopes" type
   `https://www.googleapis.com/auth/drive` and tap Authorize APIs.
   Sign in with the Google account that owns the Drive, tap
   Advanced, "Go to quiet-ledger (unsafe)", Allow. Then tap
   "Exchange authorization code for tokens" and copy the Refresh
   token.
6. In Drive, create a folder for this system. Open it and copy the
   folder id from the address bar: the long string after `folders/`
   in the URL.
7. In the repo, add two secrets: `DRIVE_OAUTH_JSON` with
   `{"client_id": "...", "client_secret": "...", "refresh_token": "..."}`
   (paste your three values in), and `DRIVE_FOLDER_ID` with the
   folder id from step 6.

### 2. The queue file

The first time a job runs, it creates `queue.json` in that Drive
folder by itself. You do not need to make it. It is only a thin
index: one entry per video with {id, topic, status, folder_id,
drive_link}. The script lives in the video's own folder, not in the
queue. To add an idea by hand, edit `queue.json` in Drive and add an
entry:

```json
{"id": 1, "topic": "Why the sky looks blue at noon", "status": "idea",
 "folder_id": null, "drive_link": null}
```

Status moves: idea, script-ready, approved, rendering, in-drive,
failed, posted. Only `approved` entries are built.

### 3. First run

1. Muse writes a script and pushes it to the repo under
   `submissions/<slug>/script.json`.
2. Open the repo, Actions, quiet-ledger, Run workflow. Leave
   queue_id empty to render the next approved entry, or type an id
   to render (or re-render) that entry.
3. The ingest job files the submission into Drive and marks it
   approved; the render chain narrates, draws, captions, assembles,
   QCs, and files the finished piece in Drive.
4. Every morning at 09:00 IST the schedule runs by itself: it ingests
   any new submission first, then builds the next approved entry,
   if there is one.

## What you provide vs what is already built

You provide: the OAuth login, the Drive folder, the topics, and the
approval of each script. Everything else in this repo is already
built: the ingest step, the narration, the scene rendering, captions,
assembly, frame QC, the thumbnail, the Drive filing, and the daily
schedule. Muse provides the script and the scene code.

## The control app (comes later)

`control-app/` holds a stub for now. After the first finished file
proves this flow end to end, a Flutter desktop app goes there: queue,
script approval, triggering, live status, Drive outputs, settings.
Desktop first, an Android build from the same code later.
