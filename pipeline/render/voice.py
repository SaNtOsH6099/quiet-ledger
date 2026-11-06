#!/usr/bin/env python3
"""Narration, one continuous take. The whole script goes to Kokoro in a
single call, segments are concatenated with no added gaps, then leading
and trailing silence is trimmed. Voice af_heart, speed 0.8 by default
(the speed the demo was approved at).

Usage: voice.py --script script.json --out narration.wav [--voice af_heart]
       [--speed 0.8]
Requires: kokoro, soundfile, numpy (see requirements-voice.txt).
"""
import argparse
import json

import numpy as np
import soundfile as sf
from kokoro import KPipeline


def narrate(text, out_path, voice="af_heart", speed=0.8):
    print("loading Kokoro...", flush=True)
    pipeline = KPipeline(lang_code="a")
    print(f"synthesising at speed {speed}, voice {voice}...", flush=True)
    chunks = []
    for i, (gs, _ps, audio) in enumerate(
        pipeline(text, voice=voice, speed=speed)
    ):
        print(f"  segment {i}: {len(audio) / 24000:.2f}s [{gs[:40]}...]",
              flush=True)
        chunks.append(audio)
    audio = np.concatenate(chunks)
    # trim leading/trailing silence, keep natural pauses inside
    absig = np.abs(audio)
    nz = np.where(absig > 0.005)[0]
    if len(nz):
        audio = audio[max(0, nz[0] - 1200): nz[-1] + 1200]
    sf.write(out_path, audio, 24000)
    print(f"saved {out_path}: {len(audio) / 24000:.2f}s, {len(audio)} samples")
    return len(audio) / 24000


def main():
    parser = argparse.ArgumentParser(description="Kokoro narration, one take")
    parser.add_argument("--script", required=True,
                        help="script.json (submitted by Muse)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--speed", type=float, default=0.8)
    args = parser.parse_args()
    text = json.load(open(args.script))["script"]
    narrate(text, args.out, args.voice, args.speed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
