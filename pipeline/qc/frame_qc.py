#!/usr/bin/env python3
"""Frame QC: catch the defects the static checks miss, on the actual
rendered video.

The CSS check and the big-text validator run on the scene code before
rendering, but they cannot see what the render actually produced.
This script runs on the finished video and checks the real frames:

Tier 1 (ffmpeg, zero new deps): blackdetect / freezedetect /
signalstats in one decode pass. Catches blank frames, frozen
segments, and near-empty or badly exposed frames.

Tier 2 (RapidOCR, one pip install): OCR on one frame per beat at the
hold point (70% through the beat, after the text has drawn in and
before the exit fade). Catches the two defects that shipped twice in
entry 3:
  - clipped text: an OCR box touching the left or right frame edge,
    or text cut mid-word at the edge.
  - missing text: a beat whose markup has a big-text element
    (hook-line, close-line, chart-title, diagram-title) but whose
    frame has no OCR text in the scene-text zone (above the caption
    zone at the bottom).

The caption zone (bottom ~30% of the frame, where the burned-in
captions sit) is excluded from the scene-text checks, so captions
never count as scene text and never trigger a clipping false
positive.

Usage: frame_qc.py --video final.mp4 --script script.json
         --timings timings.json --out qc-report.json [--work-dir work/qc]
Exit 0 when every check passes. Exit 1 with a clear error line when
a defect is found (the line starts with "frame_qc:" so the repair
job recognises it as a scene-code defect and regenerates the code).
"""
import argparse
import json
import os
import re
import subprocess
import sys

# Big-text classes: beats whose markup has one of these MUST show
# text in the scene-text zone of the rendered frame.
BIG_TEXT_CLASSES = (
    "hook-line", "close-line", "chart-title", "diagram-title",
    "hook", "close",
)
# Scene text lives above the caption zone. Captions sit at ~70% down
# the frame, so the scene-text zone is the top 65%.
SCENE_ZONE_FRACTION = 0.65
# A box is "touching" an edge when it comes within this many pixels
# of it (at the frame's native resolution).
EDGE_TOLERANCE_PX = 6


def beat_has_big_text(markup):
    """True when the beat's markup has a big-text element."""
    if not markup:
        return False
    for cls in BIG_TEXT_CLASSES:
        if f'class="{cls}"' in markup or f'class="{cls} ' in markup:
            return True
    return False


def hold_time(start, end):
    """The frame time to QC: 70% through the beat, after the text has
    drawn in and before the exit fade."""
    return start + (end - start) * 0.7


def extract_frames(video, times, work_dir):
    """Extract one frame per timestamp with ffmpeg. Returns the list
    of frame paths."""
    os.makedirs(work_dir, exist_ok=True)
    frames = []
    for i, t in enumerate(times):
        path = os.path.join(work_dir, f"beat{i + 1}.png")
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}",
            "-i", video, "-frames:v", "1", path,
        ], check=True)
        frames.append(path)
    return frames


def ffmpeg_tier(video):
    """Tier 1: blackdetect + freezedetect + signalstats in one pass.
    Returns a list of problems."""
    problems = []
    cmd = [
        "ffmpeg", "-v", "info", "-i", video,
        "-vf", "blackdetect=d=0.5:pix_th=0.10,"
               "freezedetect=n=0.003:d=0.5,"
               "signalstats",
        "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    err = r.stderr or ""
    for m in re.finditer(
            r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)",
            err):
        dur = float(m.group(3))
        if dur >= 0.5:
            problems.append(
                f"black frame interval {m.group(1)}s-{m.group(2)}s "
                f"({dur:.1f}s)")
    for m in re.finditer(
            r"freeze_start:([\d.]+) freeze_end:([\d.]+) freeze_duration:([\d.]+)",
            err):
        dur = float(m.group(3))
        if dur >= 0.5:
            problems.append(
                f"frozen frame interval {m.group(1)}s-{m.group(2)}s "
                f"({dur:.1f}s)")
    # signalstats: YAVG per frame is printed as "YAVG: nnn" lines.
    # A frame with YAVG very low and near-zero saturation is
    # effectively blank. Only flag long runs, not single frames.
    yavgs = [float(v) for v in re.findall(r"YAVG:\s*([\d.]+)", err)]
    if yavgs:
        dark = sum(1 for y in yavgs if y < 8)
        if dark > len(yavgs) * 0.5:
            problems.append(
                f"{dark}/{len(yavgs)} frames are near-black "
                "(YAVG < 8)")
    return problems


def ocr_tier(frames, script, timings):
    """Tier 2: RapidOCR on one frame per beat. Returns a list of
    problems. Requires rapidocr-onnxruntime + opencv-python-headless."""
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "RapidOCR is not installed; the text checks cannot run. "
            "Install it with: pip install rapidocr-onnxruntime "
            "opencv-python-headless") from e
    from PIL import Image  # noqa: PLC0415

    engine = RapidOCR()
    problems = []
    beats = script.get("beats", [])
    code = script.get("code", [])
    for i, frame in enumerate(frames):
        beat_no = i + 1
        w, h = Image.open(frame).size
        scene_zone_bottom = h * SCENE_ZONE_FRACTION
        result, _ = engine(frame)
        lines = []
        if result:
            for box, text, conf in result:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                lines.append({
                    "text": text,
                    "conf": float(conf),
                    "x1": min(xs), "x2": max(xs),
                    "y1": min(ys), "y2": max(ys),
                })
        # Scene-text lines: above the caption zone. Captions sit at
        # the bottom, so they never count as scene text. A single
        # stray character (a circle misread as "O", a tick mark) is
        # not text: only lines with at least 2 characters count.
        scene_lines = [
            ln for ln in lines
            if ln["y2"] <= scene_zone_bottom
            and len(ln["text"].strip()) >= 2
        ]
        # Clipped text: a scene-text box touching the left or right
        # edge of the frame.
        for ln in scene_lines:
            if ln["x1"] <= EDGE_TOLERANCE_PX:
                problems.append(
                    f"beat {beat_no}: text clipped at the LEFT edge: "
                    f"{ln['text'][:40]!r}")
            if ln["x2"] >= w - EDGE_TOLERANCE_PX:
                problems.append(
                    f"beat {beat_no}: text clipped at the RIGHT edge: "
                    f"{ln['text'][:40]!r}")
        # Missing text: the markup has a big-text element but the
        # frame shows no scene text in the scene-text zone.
        markup = ""
        if i < len(code):
            markup = code[i].get("markup", "")
        if beat_has_big_text(markup) and not scene_lines:
            idea = beats[i].get("idea", "")[:50] if i < len(beats) else ""
            problems.append(
                f"beat {beat_no}: big text is in the markup but NO "
                f"scene text is visible in the frame ({idea})")
    return problems


def main():
    parser = argparse.ArgumentParser(description="frame QC on the video")
    parser.add_argument("--video", required=True, help="finished mp4")
    parser.add_argument("--script", required=True, help="script.json")
    parser.add_argument("--timings", required=True, help="timings.json")
    parser.add_argument("--out", required=True, help="qc report json")
    parser.add_argument("--work-dir", default="work/qc",
                        help="where to put extracted frames")
    parser.add_argument("--skip-ocr", action="store_true",
                        help="run only the ffmpeg tier (no RapidOCR)")
    args = parser.parse_args()

    script = json.load(open(args.script))
    timings = json.load(open(args.timings))
    beats = timings.get("beats", [])
    if not beats:
        print("frame_qc: timings.json has no beats", file=sys.stderr)
        return 2
    times = [hold_time(b["start"], b["end"]) for b in beats]
    frames = extract_frames(args.video, times, args.work_dir)
    print(f"extracted {len(frames)} beat frames", flush=True)

    problems = ffmpeg_tier(args.video)
    if not args.skip_ocr:
        problems.extend(ocr_tier(frames, script, timings))

    report = {
        "video": args.video,
        "beats_checked": len(frames),
        "problems": problems,
        "pass": not problems,
    }
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    if problems:
        print("frame_qc: FAILED — defects found:", file=sys.stderr)
        for p in problems:
            print(f"  frame_qc: {p}", file=sys.stderr)
        return 1
    print("frame_qc: PASS — no defects found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
