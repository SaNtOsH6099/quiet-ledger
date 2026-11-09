#!/usr/bin/env python3
"""Assemble an Echoes Originals short from LOCKED clips — GitHub render step.

This follows the local 24 fps chain used for videos 65-78 (see
~/workspace/video-tools/antikythera-79/work/assemble_clean.sh and
finish_clean.sh for the reference implementation), ported to a
parameterised script:

Inputs (all produced locally by the per-video side chat, already in the
per-video Drive folder in quiet-ledger, fetched by echoes_intake.py):
  --segments-dir  locked AI clips, one mp4 per segment (10s each, 24 fps;
                    usually landscape 1280x720, sometimes a still-animated
                    frame of another size)
  --segment-map   segment_map.json: [{"file": "C1.mp4", "start": 0.0,
                    "end": 9.4}, ...] — start/end are TIMELINE times in
                    the narration; each segment is trimmed from the START
                    of its own clip for (end - start) seconds. Trim only,
                    never setpts slowing.
  --captions      captions-24fps.mp4 from echoes_captions.py (HyperFrames
                    karaoke, 1080x1920, 24 fps, black background, white
                    text, gold keywords)
  --audio         narration mix wav (Gemini Kore, one take, -23 LUFS mix)
  --out           final mp4

Steps:
  1. Per segment, blur-fill to 1080x1920 (background scale-to-cover +
     gblur sigma=40 + brightness -0.25; foreground centred at width
     1080, height from the clip's aspect, y = (1920 - fg_h) / 2),
     trimmed to its duration, CRF 18, preset medium, 24 fps. If a
     segment is longer than its 10s clip, the excess is a tpad hold
     (stop_mode=clone) of the last frame — never a known lead.
  2. Concat the trimmed segments, and GUARD: concat must be >= the
     narration mix, or -shortest would truncate the narration. Fail
     loudly here, do not mux a short chain.
  3. Mux the narration (-shortest cuts at the mix length), then a 0.5s
     tail: audio apad 0.5 + video tpad clone 0.5, so the last word is
     actually heard.
  4. Composite the caption mp4, padded with tpad clone to the tailed
     length, by blend in RGB. The magenta bug: blending on YUV420p
     turns magenta, so both inputs are converted to RGB (format=gbrp)
     before blend=all_mode=screen, then back to yuv420p. Screen blend
     makes the caption video's black background disappear.
  5. Measure the composite's loudness (no -v error: the Parsed_loudnorm
     JSON prints at INFO level and -v error suppresses it).
  6. Cinema finish, in the final encode: hqdn3d denoise, eq grade,
     colorbalance (warm highlights / cool shadows), unsharp, vignette,
     film grain noise=alls=7, fade-out in the last 0.5s only (NO fade-in).
     Two-pass loudnorm to -23 LUFS (TP -2, LRA 11): apply with the
     measured values and linear=true. libx264 CRF 15, preset slow,
     1080x1920, 24 fps, maxrate 20M, yuv420p, faststart.
  7. Verify: 1080x1920, 24 fps, duration within 0.5s of mix + 0.5s tail,
     loudness within 0.5 LUFS of -23. Fail loudly on any mismatch.

There is NO size cap. Echoes finals are 180-310 MB; the old assemble.py
failed anything over 100 MB. That cap is gone.
"""
import argparse
import json
import os
import re
import subprocess
import sys


def run(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-show_entries", "format=duration,size",
         "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    d = json.loads(out.stdout)
    stream = d["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": int(num) / int(den),
        "duration": float(d["format"]["duration"]),
        "size": int(d["format"]["size"]),
    }


def probe_audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def measure_loudness(path):
    """First loudnorm pass: measure only, return the measured values.

    No -v error here: the Parsed_loudnorm JSON prints at INFO level
    and -v error suppresses it (the 65 lesson).
    """
    out = subprocess.run(
        ["ffmpeg", "-i", path, "-vn", "-sn", "-dn",
         "-af", "loudnorm=I=-23:TP=-2:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    text = out.stderr
    m = re.search(r"\{[^}]*\"input_i\"[^}]*\}", text, re.S)
    if not m:
        raise RuntimeError("loudnorm measurement produced no JSON:\n" + text[-2000:])
    return json.loads(m.group(0))


def blur_fill_filter(width, height):
    """Blur-fill a (usually landscape) clip into 1080x1920."""
    fg_h = round(1080 * height / width)
    fg_y = (1920 - fg_h) // 2
    return (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,gblur=sigma=40,eq=brightness=-0.25[bg];"
        f"[0:v]scale=1080:{fg_h}[fg];"
        f"[bg][fg]overlay=(W-w)/2:{fg_y},fps=24,format=yuv420p"
    )


def main():
    parser = argparse.ArgumentParser(
        description="assemble an Echoes short from locked clips")
    parser.add_argument("--segments-dir", required=True)
    parser.add_argument("--segment-map", required=True)
    parser.add_argument("--captions", required=True,
                        help="captions-24fps.mp4 (HyperFrames, 24 fps)")
    parser.add_argument("--audio", required=True, help="narration mix wav")
    parser.add_argument("--out", required=True)
    parser.add_argument("--work-dir", default="work/assemble")
    args = parser.parse_args()

    with open(args.segment_map) as f:
        segments = json.load(f)
    if not segments:
        raise SystemExit("segment map is empty")
    total = max(float(s["end"]) for s in segments)
    mix_dur = probe_audio_duration(args.audio)
    print(f"{len(segments)} segments, timeline total {total:.2f}s, "
          f"narration mix {mix_dur:.2f}s")
    if abs(total - mix_dur) > 1.0:
        print(f"warning: segment timeline {total:.2f}s and mix "
              f"{mix_dur:.2f}s differ by more than 1s", file=sys.stderr)

    os.makedirs(args.work_dir, exist_ok=True)
    trimmed = []
    for i, seg in enumerate(segments):
        src = os.path.join(args.segments_dir, seg["file"])
        dur = float(seg["end"]) - float(seg["start"])
        if dur <= 0:
            raise SystemExit(f"segment {i} ({seg['file']}): bad duration {dur}")
        info = probe(src)
        out = os.path.join(args.work_dir, f"seg{i:02d}.mp4")
        # Trim from the START of this clip, for the segment duration.
        clip_dur = min(dur, info["duration"])
        run(["ffmpeg", "-y", "-v", "error", "-i", src,
             "-t", f"{clip_dur:.3f}",
             "-filter_complex", blur_fill_filter(info["width"], info["height"]),
             "-r", "24", "-an",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", out])
        if dur > info["duration"]:
            # Segment longer than its clip: hold the last frame.
            held = os.path.join(args.work_dir, f"seg{i:02d}_held.mp4")
            hold = dur - info["duration"]
            run(["ffmpeg", "-y", "-v", "error", "-i", out,
                 "-vf", f"tpad=stop_duration={hold:.3f}:stop_mode=clone,fps=24",
                 "-r", "24", "-an",
                 "-c:v", "libx264", "-crf", "18", "-preset", "medium", held])
            out = held
            print(f"segment {i}: hold {hold:.3f}s (clip only "
                  f"{info['duration']:.2f}s)")
        trimmed.append(out)

    concat_list = os.path.join(args.work_dir, "concat.txt")
    with open(concat_list, "w") as f:
        for p in trimmed:
            f.write(f"file '{os.path.abspath(p)}'\n")
    silent = os.path.join(args.work_dir, "silent.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", silent])
    concat_dur = probe(silent)["duration"]
    print(f"concat {concat_dur:.2f}s (mix {mix_dur:.2f}s)")
    if concat_dur < mix_dur:
        raise SystemExit("CONCAT TOO SHORT — STOP, do not mux a short chain")

    with_audio = os.path.join(args.work_dir, "with_audio.mp4")
    run(["ffmpeg", "-y", "-v", "error",
         "-i", silent, "-i", args.audio,
         "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", with_audio])

    tailed = os.path.join(args.work_dir, "with_tail.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-i", with_audio,
         "-filter_complex",
         "[0:a]apad=pad_dur=0.5[a];"
         "[0:v]tpad=stop_duration=0.5:stop_mode=clone,fps=24[v]",
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-c:a", "aac", "-b:a", "192k", "-r", "24", tailed])
    tailed_dur = probe(tailed)["duration"]

    composited = os.path.join(args.work_dir, "composite.mp4")
    cap_pad = tailed_dur - probe(args.captions)["duration"]
    run(["ffmpeg", "-y", "-v", "error",
         "-i", tailed, "-i", args.captions,
         "-filter_complex",
         f"[1:v]tpad=stop_duration={max(cap_pad, 0):.3f}:stop_mode=clone,"
         "fps=24[cap];[0:v]format=gbrp[v0];[cap]format=gbrp[cap2];"
         "[v0][cap2]blend=all_mode=screen,format=yuv420p,fps=24[v]",
         "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-c:a", "copy", "-r", "24", composited])

    # Two-pass loudnorm: measure, then finish with measured values.
    measured = measure_loudness(composited)
    print("loudnorm measured:", json.dumps(measured))
    video_filter = (
        "hqdn3d=1.5:1.5:6:6,eq=contrast=1.10:saturation=1.18:brightness=0.02,"
        "colorbalance=gs=-0.04:bs=0.06:rh=0.04:gh=0.01,"
        "unsharp=5:5:0.5:5:5:0.0,vignette=PI/5,"
        "noise=alls=7:allf=t+u,"
        f"fade=t=out:st={mix_dur:.3f}:d=0.5,format=yuv420p"  # mix end, not timeline total: the last segment may carry 0.5s headroom
    )
    loudnorm = (
        "loudnorm=I=-23:TP=-2:LRA=11:"
        f"measured_I={measured['input_i']}:"
        f"measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:"
        f"measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true"
    )
    run(["ffmpeg", "-y", "-v", "error", "-i", composited,
         "-vf", video_filter, "-af", loudnorm,
         "-c:v", "libx264", "-preset", "slow", "-crf", "15",
         "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
         "-r", "24", "-maxrate", "20M", "-bufsize", "40M",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         args.out])

    info = probe(args.out)
    print(f"wrote {args.out}: {info['size']} bytes, "
          f"{info['duration']:.2f}s, {info['width']}x{info['height']}, "
          f"{info['fps']:.2f} fps")
    errors = []
    if (info["width"], info["height"]) != (1080, 1920):
        errors.append(f"resolution {info['width']}x{info['height']} != 1080x1920")
    if abs(info["fps"] - 24) > 0.1:
        errors.append(f"fps {info['fps']:.2f} != 24")
    if abs(info["duration"] - (mix_dur + 0.5)) > 0.5:
        errors.append(f"duration {info['duration']:.2f}s != "
                      f"expected {mix_dur + 0.5:.2f}s")
    final_loudness = measure_loudness(args.out)
    print("final loudness:", json.dumps(final_loudness))
    if abs(float(final_loudness["input_i"]) - (-23)) > 0.5:
        errors.append(f"loudness {final_loudness['input_i']} LUFS != -23")
    if errors:
        for e in errors:
            print("VERIFY FAILED: " + e, file=sys.stderr)
        return 1
    print("verify passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
