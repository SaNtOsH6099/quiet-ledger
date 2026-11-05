# Control app (stub)

The desktop control app lives here later, after the first finished
file proves the flow end to end. It is a Flutter app: one codebase,
desktop first, an Android build from the same code later.

It is a thin client. It only uses the internet to talk to GitHub and
Drive. No rendering or heavy work happens on your machine, and nothing
about the queue is public.

What it will control:

- Queue: add topics, reorder, see every entry and its status.
- Script approval: read the draft, approve it or ask for a rewrite.
- Triggering: start a draft run or a full build run.
- Live status: see what each run is doing, and read the logs when one
  fails.
- Drive outputs: list finished files, watch them, mark them posted.
- Brain switch: pick which provider drafts next, and see how many
  keys each provider has left.
- Settings: repo, Drive folder, and keys stored on the device only.

Nothing is built here yet on purpose. The flow comes first, the
remote control second.
