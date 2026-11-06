#!/usr/bin/env python3
"""Assemble the finished file: silent drawn frames + narration + captions.

Steps, from the approved demo:
  1. loudnorm the narration to -23 LUFS (single pass, linear).
  2. Mux frames + narration, burn the captions in, add light animated grain.
Output: 1080x1920, 30fps, H.264 crf 20, AAC 128k, faststart. Fails if the
result is over 100MB.
"""
import argparse
import json
import subprocess
import sys


def run(cmd, **kw):
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def main():
    parser = argparse.ArgumentParser(description="assemble the finished file")
    parser.add_argument("--video", required=True, help="silent drawn frames")
    parser.add_argument("--audio", required=True, help="narration wav")
    parser.add_argument("--captions", required=True, help="captions.ass")
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=float, default=None,
                        help="total seconds; default is the frame length")
    parser.add_argument("--norm-audio", default="narration-norm.wav")
    args = parser.parse_args()

    total = args.duration or probe_duration(args.video)
    print(f"total duration: {total:.2f}s")

    run(["ffmpeg", "-y", "-v", "error", "-i", args.audio,
         "-af", "loudnorm=I=-23:TP=-2:LRA=11:linear=true",
         args.norm_audio])
    run(["ffmpeg", "-y", "-v", "error",
         "-i", args.video, "-i", args.norm_audio,
         "-filter_complex",
         f"[0:v]subtitles={args.captions}[v1];"
         "[v1]noise=alls=5:allf=t[vout]",
         "-map", "[vout]", "-map", "1:a",
         "-c:v", "libx264", "-crf", "20", "-maxrate", "8M", "-bufsize", "16M",
         "-preset", "fast", "-pix_fmt", "yuv420p", "-r", "30",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
         "-t", f"{total:.2f}", args.out])

    import os
    size = os.path.getsize(args.out)
    print(f"wrote {args.out}: {size / 1e6:.1f}MB, {probe_duration(args.out):.2f}s")
    if size > 100 * 1024 * 1024:
        print("error: finished file is over 100MB", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
