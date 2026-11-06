# Setup checklist

Tick each box off as you go. Nothing here costs money and nothing
needs a card.

## Keys (repo Settings, Secrets and variables, Actions)

No brain keys: no model is called from Actions, so there is nothing
to add here. (The Groq, Gemini and NVIDIA keys from the old setup are
no longer used by the pipeline. They can be deleted from the repo
secrets, or left in place; the workflow never reads them.)

## Drive (see README section 1 for the step-by-step)

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

- [ ] Muse writes a script and pushes it to `submissions/<slug>/script.json`
- [ ] Actions, quiet-ledger, Run workflow (queue_id empty: next approved entry)
- [ ] Ingest files the submission into Drive and marks it approved
- [ ] Finished file and thumbnail found in the Drive folder
- [ ] Watched it, happy with it

## After the first finished file

- [ ] Daily schedule left on (09:00 IST, ingests any new submission, builds the next approved entry)
- [ ] Control app build starts (see `control-app/README.md`)
