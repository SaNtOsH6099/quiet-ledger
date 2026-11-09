#!/usr/bin/env bash
# Render the current Echoes captions composition at 24 fps (the jitter fix).
#
# WHY THIS SCRIPT EXISTS (2026-11-07): the captions render used to be run as a
# long inline `npx hyperframes@0.9.2 render ... -o renders/<video>-captions.mp4`
# command. Because the output filename changed every video, the runtime treated
# each render as a brand-new command and showed a fresh approval card every
# time (59 v2 and 61 both paused waiting for one; the 61 card sat undecided
# for ~2h43m). In batch 45-55 the render went through tools/render_echoes.sh
# — one stable script invocation — and never asked like this.
#
# This script restores that pattern for the 24 fps chain: it takes NO
# arguments, so the invocation is byte-identical for every video, and it
# always renders to the SAME fixed file. Rename the output afterwards:
#
#   bash tools/render_captions_24fps.sh
#   mv renders/captions-24fps.mp4 renders/<video>-captions.mp4
#
# The composition (index.html) is overwritten per video by
# `python3 tools/build_captions.py captions/<name>.json index.html` before
# this script runs, so the fixed output always holds the current video.
# 24 fps, portrait 1080x1920, delivery quality, keyframe every 2s, 1 worker,
# frames cache inside this project (NOT /tmp, a 512 MB tmpfs).
# No `check` step here: the inline 24 fps renders that proved this command
# (57v2, 58v2, 59v2, 60v2, 61, 62) ran without it.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p renders .cache/frames .cache/tmp
export TMPDIR="$PWD/.cache/tmp"
export HYPERFRAMES_EXTRACT_CACHE_DIR="$PWD/.cache/frames"

npx --yes hyperframes@0.9.2 render . \
  -o renders/captions-24fps.mp4 \
  --fps 24 \
  --resolution portrait \
  --quality delivery \
  --keyframe-interval 2 \
  --low-memory-mode \
  --workers 1 \
  --frames-cache-dir "$PWD/.cache/frames"
