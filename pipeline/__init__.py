"""quiet-ledger pipeline, organized by stage.

Each stage reads its input from a file and writes its output to a file;
the handoff between stages is the file, never shared memory. See
PIPELINE.md for the stage list and what each stage consumes and produces.

Stages:
  brain      the brain: draft the script + beats, then write the scene code
  guardrails the rules that keep the video from breaking (format-specific)
  render     turn code + narration into the finished video
  drive      Google Drive: the queue and the finished-file upload
  repair     self-heal: fix a failed render and retry it
  tools      checks that guard the pipeline itself
"""
