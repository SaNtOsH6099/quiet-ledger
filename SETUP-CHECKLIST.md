# Setup checklist

Tick each box off as you go. Nothing here costs money and nothing
needs a card.

## Keys (repo Settings, Secrets and variables, Actions)

- [ ] `GROQ_API_KEYS`: free keys from console.groq.com, comma-separated
- [ ] `GEMINI_API_KEYS`: free keys from Google AI Studio, comma-separated
- [ ] `NVIDIA_API_KEYS`: free nvapi- keys from build.nvidia.com, comma-separated (fallback only, optional for now)

## Drive (see README section 2 for the step-by-step)

- [ ] Google Cloud project created, Drive API enabled
- [ ] Service account created, JSON key downloaded
- [ ] Drive folder created and shared with the service account (Editor)
- [ ] `DRIVE_SERVICE_ACCOUNT_JSON`: whole JSON file pasted as a secret
- [ ] `DRIVE_FOLDER_ID`: folder id from the Drive URL, as a secret

## First run

- [ ] Actions, quiet-ledger, Run workflow, stage `draft`, with a topic
- [ ] Draft artifact downloaded, `script.md` read
- [ ] Queue entry in Drive changed to `approved`
- [ ] Run workflow again, stage `render`
- [ ] Finished file and thumbnail found in the Drive folder
- [ ] Watched it, happy with it

## After the first finished file

- [ ] Daily schedule left on (09:00 IST, builds the next approved entry)
- [ ] Control app build starts (see `control-app/README.md`)
