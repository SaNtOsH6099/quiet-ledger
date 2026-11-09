# Setup checklist — Echoes Originals (quiet-ledger)

Tick each box off as you go. Nothing here costs money and nothing
needs a card.

## Secrets (repo Settings → Secrets and variables → Actions)

No brain keys: no model is called from Actions, so there is nothing
to add here. Narration is Gemini Kore, made locally by the per-video
side chat; captions are measured locally; clips are generated locally.

- [x] `DRIVE_OAUTH_JSON`: Google OAuth client id, client secret and
  refresh token as one JSON secret (working auth, verified by a real
  dispatch on 2026-11-09)
- [x] `DRIVE_FOLDER_ID`: the quiet-ledger Drive folder id, as a secret

Note: a service account does NOT work here. Service accounts have no
storage quota, so Google refuses file creation in a personal Drive
folder. `DRIVE_SERVICE_ACCOUNT_JSON` is not used by `echoes-render`
and should be removed from repo secrets, along with the old Groq,
Gemini and NVIDIA keys from the failed experiment (the GitHub PAT
cannot list or remove secrets, so remove them in the GitHub UI).

## Drive (see README for the flow)

- [x] Google Cloud project created, Drive API enabled
- [x] OAuth consent screen set up (External) and app published
- [x] Web OAuth client created, refresh token obtained
- [x] Drive folder `quiet-ledger` is the staging hub; `svg assets/`
  inside it is the old SVG pack (kept, Echoes does not use it)

## First render (test, before switching the live batch)

- [x] Test staging folder created in quiet-ledger (not Echoes Drop)
- [x] Locked clips + narration + captions.json + segment_map.json
  uploaded into it
- [x] `echoes-render` dispatched (see `scripts/dispatch_echoes_render.py`)
- [x] Final returned to the staging folder; size, duration and
  loudness verified against the shipped video
- [x] Test staging folder cleaned (Drive trash, recoverable)

## After the first finished render

- [ ] Hub does local frame QA on the returned final
- [ ] Hub transfers final + narration-timestamps to Echoes Drop
- [ ] Hub cleans the staging folder
- [ ] User decides when the live batch switches to this flow
