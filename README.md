# quiet-ledger

A small personal system that turns a written idea into a finished
narrated file. It drafts the words, draws every scene in code, narrates
them in one continuous take, assembles the finished file, and files it
in Drive for review. Nothing here costs money and nothing needs a card.

Every visual is drawn in code: line drawings, animated charts, stick
figures, diagrams, kinetic text. No photos, no stock, no generated
imagery of any kind.

## How one idea becomes a finished file

1. An idea goes into the queue (a `queue.json` file in Drive).
2. The brain drafts the script and the scene plan (script + scenes).
3. You read the draft and approve it.
4. Kokoro narrates it in one continuous take.
5. Code draws the scenes from the scene plan.
6. faster-whisper times every word; captions are built in 3 to 4 word
   chunks, bold white with a black outline, lower third.
7. ffmpeg assembles the finished file: 1080x1920, 30fps, -23 LUFS,
   light grain.
8. A thumbnail is drawn in code.
9. The finished file and thumbnail land in Drive.
10. You watch it in Drive and post it yourself, by hand.

Steps 2 to 9 run on GitHub's machines, not yours. Your machine never
renders anything.

## The brain

The draft step tries providers in this order, and stops at the first
one that returns a valid draft:

1. Groq (gpt-oss-120b), primary
2. Gemini (Flash)
3. NVIDIA NIM hosted (Nemotron), fallback leg only
4. A small local model, if one is configured, last resort

You can hold several keys per provider. Each provider's keys go in one
secret as a comma-separated list, and the rotation tries each key in
order: on a rate limit or an auth error it moves to the next key, and
only when every key of a provider is exhausted does it move to the
next provider.

Honest caveat: NVIDIA's own FAQ says its free hosted access is for
prototyping only, so it sits third in line as a fallback, never as the
primary brain. If it ever stops working, the rotation simply skips it.

## Setup

You need four things. Everything below is free and needs no card.

### 1. Brain keys

Create free keys and paste each provider's keys as ONE comma-separated
secret (no spaces needed, commas only):

| Secret | Where to get the keys |
|---|---|
| `GROQ_API_KEYS` | console.groq.com, API Keys, create one per account you hold |
| `GEMINI_API_KEYS` | Google AI Studio, Get API key, one per account you hold |
| `NVIDIA_API_KEYS` | build.nvidia.com, generate an nvapi- key, one per account you hold |

Add them in the repo: Settings, Secrets and variables, Actions, New
repository secret. The Groq and Gemini secrets are the ones that
matter; NVIDIA is a fallback and can be added later.

### 2. Google Drive access (OAuth as you)

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

### 3. The queue file

The first time a job runs, it creates `queue.json` in that Drive
folder by itself. You do not need to make it. To add an idea by hand,
edit `queue.json` in Drive and add an entry:

```json
{"id": 1, "topic": "Why the sky looks blue at noon", "status": "idea",
 "script": null, "scenes": null, "drive_link": null}
```

Status moves: idea, script-ready, approved, rendering, in-drive,
posted. Only `approved` entries are built.

### 4. First run

1. Open the repo, Actions, quiet-ledger, Run workflow.
2. Set stage to `draft` and type a topic. Run it.
3. When it finishes, download the `draft` artifact and read
   `script.md`. That is the script and the scene plan.
4. If you like it, open `queue.json` in Drive and change that entry's
   status to `approved`. If not, change the topic and draft again.
5. Run the workflow again with stage `render`. It narrates, draws,
   captions, assembles, and files the finished piece in Drive.
6. Every morning at 09:00 IST the schedule runs by itself and builds
   the next approved entry, if there is one.

## What you provide vs what is already built

You provide: the keys above, the OAuth login, the Drive folder,
the topics, and the approval of each script. Everything else in this
repo is already built: the draft step with its four-way rotation, the
narration, the five drawn scene types, captions, assembly, the
thumbnail, the Drive filing, and the daily schedule.

## The control app (comes later)

`control-app/` holds a stub for now. After the first finished file
proves this flow end to end, a Flutter desktop app goes there: queue,
script approval, triggering, live status, Drive outputs, brain switch,
settings. Desktop first, an Android build from the same code later.
