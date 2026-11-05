# Setup checklist

Tick each box off as you go. Nothing here costs money and nothing
needs a card.

## Keys (repo Settings, Secrets and variables, Actions)

- [x] `GROQ_API_KEYS`: free keys from console.groq.com, comma-separated
- [x] `GEMINI_API_KEYS`: free keys from Google AI Studio, comma-separated
- [ ] `NVIDIA_API_KEYS`: free nvapi- keys from build.nvidia.com, comma-separated (fallback only, optional for now)

## Drive (see README section 2 for the step-by-step)

- [x] Google Cloud project created, Drive API enabled
- [x] OAuth consent screen set up (External) and app published to Production
- [x] Web OAuth client created, Playground redirect URI added
- [x] Refresh token obtained via the OAuth Playground
- [x] `DRIVE_OAUTH_JSON`: client id, client secret and refresh token as one JSON secret
- [x] `DRIVE_FOLDER_ID`: folder id from the Drive URL, as a secret

Note: a service account does NOT work here. Service accounts have no
storage quota, so Google refuses file creation in a personal Drive
folder. That is why the pipeline signs in as you through OAuth.

## First run

- [x] Actions, quiet-ledger, Run workflow, stage `draft`, with a topic
- [ ] Draft artifact downloaded, `script.md` read
- [ ] Queue entry in Drive changed to `approved`
- [ ] Run workflow again, stage `render`
- [ ] Finished file and thumbnail found in the Drive folder
- [ ] Watched it, happy with it

## After the first finished file

- [ ] Daily schedule left on (09:00 IST, builds the next approved entry)
- [ ] Control app build starts (see `control-app/README.md`)
