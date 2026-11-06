"""quiet-ledger pipeline, organized by stage.

Each stage reads its input from a file and writes its output to a file;
the handoff between stages is the file, never shared memory. See
PIPELINE.md for the stage list and what each stage consumes and produces.

Stages:
  guardrails the rules that keep the video from breaking (format-specific)
  validate   check Muse-written scene code against the guardrails
  render     turn code + narration into the finished video
  drive      Google Drive: the queue, ingest, and the finished-file upload
  qc         frame QC on the finished video, before upload
  tools      checks that guard the pipeline itself

Muse is the brain and works outside Actions: topic, script, beats,
scene code, validation, and a demo render. GitHub Actions is only the
rendering machine: ingest, narration, scenes, captions, assembly, QC,
thumbnail, upload. No model is called from Actions, and no brain keys
are needed.
"""
