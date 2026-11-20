#!/usr/bin/env python3
"""Assemble an Echoes Originals short from LOCKED clips — GitHub render step, v2.

DRAFT — NOT YET TESTED IN ACTIONS. Derived from pipeline/render/
echoes_assemble.py (v1) on 2026-11-18. v2 changes (each traces to an
audit gap in AUDIT.md):
  G1 tail freeze: caption text+plate layers are PRE-EXTENDED as
     standalone files (trim at the last full-opacity frame + tpad
     clone) BEFORE compositing; the composite graph carries NO
     trim/tpad (v1's tpad-inside-the-graph does not take effect —
     64 Gate 3 v1 defect). Needs --captions-json to find the last
     full-opacity frame.
  G4 grade: the v1 finish used the PRE-FIX 58 grade (brightness 0.02,
     vignette PI/5 — red-team failed as too dark). v2 uses the current
     local finish: brightness 0.06, vignette PI/7, hqdn3d 4:4:6:6,
     unsharp 0.6, grain alls=7:allf=t+u.
  G5 silent holds: a segment longer than its clip now FAILS instead of
     silently holding the last frame (NO HOLDS rule); the concat
     shortfall pad is capped at 0.05s (frame quantisation) and fails
     above it.
  G3 still beats: segment files may be STILL IMAGES (.jpg/.jpeg/.png/
     .webp) — the segment is built by looping the still for the segment
     duration. This is what the modified pipeline needs: it is
     stills-dominant, so most segments are stills, not clips.
  KEN BURNS RENDERED ON THE RUNNER (SOLVED 2026-11-19): a segment
     asking for a Ken Burns move carries a "kenburns" dict in the
     segment map — {"zoom0", "zoom1", "cx0", "cy0", "cx1", "cy1"} —
     and the assemble step renders it with kenburns_v2.py (OpenCV
     subpixel warp, the PROVEN prototype) into an mp4 before the
     concat. The lesson-50 clamp (1/(2z) <= c <= 1-1/(2z)) is
     asserted on the runner; --verify-only validates the spec
     without rendering. Never ffmpeg zoompan (it vibrates on fine
     detail, 58 Gap1). Anything the KB step cannot render — a string
     spec, a missing key, a clamp violation, an unreadable still, no
     OpenCV on the runner — FAILS LOUDLY; never a still or a zoompan
     substituted silently.
  FRAME-PINNED ENCODE + CONCAT (mini-test run 2 fix, 2026-11-18):
     the segment encode used "-t {dur}" with an fps=24 filter, and
     the concat used "-f concat -c copy". Both are version-sensitive:
     on the mini test "-t 0.520" dropped the tail clip's 13th frame
     (at 0.5s) on local ffmpeg 8.1.2, and the GitHub runner's ffmpeg
     6.1.1 lost 2 more frames somewhere in the chain — the concat
     came out 19.29s against a 19.40s mix and the G5 guard stopped
     the run. The encode now pins the frame count with "-frames:v N"
     (N = round(dur * 24)) and the concat re-encodes through the
     concat filter, so the chain's frame count is exactly the sum of
     the segment frames on any ffmpeg version — no -t boundary
     rounding, no demuxer gap-fill. The 0.05s shortfall pad stays as
     the quantisation tolerance only.
  NO fps FILTER ANYWHERE (mini-test run 3 fix, 2026-11-18): run 3
     used the frame pin and STILL came out 19.29s. Reproduced
     locally with ffmpeg 6.1.1 (the version the GitHub runner apt-
     installs): the fps=24 filter in the blur-fill chain drops the
     LAST frame of a 213f input (212 out) and of a 240f input (239
     out) — 212+239+12 = 463f = 19.29s, exactly the GitHub number.
     ffmpeg 8.1.2 does not drop it. So the fps filter is the root
     cause, not the concat: every fps=24 filter is REMOVED from this
     script (segment encode, concat, tpad pad, tail, composite) and
     the rate is pinned by the "-r 24" output option instead, which
     does not drop frames. Any future fps filter here must be
     re-proven against ffmpeg 6.1.1, not just the local build.
  VERIFY-ONLY (Hub correction 2026-11-19): --verify-only runs every
     input check the encode path enforces (segment files exist,
     durations vs windows incl. the G5 hold refusal, frame-pinned
     concat vs mix, captions JSON vs layers) and exits without
     encoding anything. The local cinema twin was a duplicate render
     — 70 is the LAST video that gets one; 71+ pre-flight is
     verify-only, and Gate 4 reviews the GitHub render as it lands.
  LAST-FRAME LUMA ASSERTION (65 Gate 4 F1, 2026-11-20): after the
     finish encode, the final frame's mean RGB luma must be < 10
     (63 v2 measured 5.68; the failed 65 v1 measured 18.38) — the
     0.5s tail fade must complete. Run 44742850858 applied the
     correct fade (st=64.000:d=0.5, confirmed from its assemble job
     log) yet the fade ran at half rate on that runner, so a correct
     filter is not enough: the render must fail loudly here instead
     of shipping mid-fade.

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
                    never setpts slowing. A Ken Burns segment is a
                    still image plus a "kenburns" dict {"zoom0",
                    "zoom1", "cx0", "cy0", "cx1", "cy1"} — rendered on
                    the runner by kenburns_v2.py (lesson-50 clamp
                    asserted); see the KEN BURNS note above.
  --captions      captions-24fps.mp4 from echoes_captions.py (HyperFrames
                    karaoke, 1080x1920, 24 fps, black background, white
                    text, gold keywords)
  --captions-plates
                    captions-plates-24fps.mp4 from echoes_captions.py
                    (Hormozi only: white background, dark per-word
                    plates). Multiplied onto the footage BEFORE the text
                    layer is screened on top. Omit for legacy captions
                    (no plates file exists) and for caption-free renders.
  --audio         narration mix wav (Gemini Kore, one take, -23 LUFS mix)
  --out           final mp4

Steps:
  1. Per segment, blur-fill to 1080x1920 (background scale-to-cover +
     gblur sigma=40 + brightness -0.25; foreground centred at width
     1080, height from the clip's aspect, y = (1920 - fg_h) / 2),
     frame-pinned to round(dur * 24) frames, CRF 18, preset medium,
     24 fps. If a segment is longer than its clip, FAIL loudly (G5 —
     no silent hold; re-type as a still beat or re-cut). A still-image
     segment is looped for its frame count (G3).
  2. Concat the trimmed segments through the concat filter
     (re-encode, so the frame count is exactly the sum of the
     segments), and GUARD: concat must be >= the narration mix, or
     the video would end before the narration. Fail loudly here, do
     not mux a short chain. A shortfall of at most 0.05s (frame
     quantisation) is padded; anything more fails (G5).
     THE VIDEO CHAIN IS THE FINAL LENGTH. The timeline total is the
     last word + 0.5s by construction (69: 2181f = 90.88s), so the
     concat already runs 0.5s past the last word. There is NO tail
     step: no -shortest cut of the video, no tpad clone of the last
     frame. (69 Gate 4 Defect 2: the v1 code cut the video to the
     mix with -shortest, then tpadded 12 clone frames under the
     fade — a frozen tail. That is banned.)
  3. Mux the narration, padding the AUDIO with silence (apad) to
     the video length. The mix is shorter than the video chain by
     the tail (69: mix 90.58s, video 90.88s), so apad adds ~0.3s
     of silence after the mix's own trailing silence. The last
     word is heard, then 0.5s of moving S18 under the fade.
  4. Pre-extend the caption text+plate layers as standalone files
     (trim at the last full-opacity frame + tpad clone, frame counts
     verified — G1), then composite by blend in RGB with NO trim/tpad
     in the composite graph (tpad inside the graph does not take
     effect). The magenta bug: blending on YUV420p turns magenta, so
     both inputs are converted to RGB (format=gbrp) before
     blend=all_mode=screen, then back to yuv420p. Screen blend makes
     the caption video's black background disappear.
     Hormozi: the plate video (white background, dark per-word plates)
     is multiplied onto the footage FIRST — multiply makes its white
     background disappear and darkens the footage under each plate —
     then the text layer is screened on top:
     [v0][plate2]blend=all_mode=multiply[vm];
     [vm][cap2]blend=all_mode=screen. The plate video is pre-extended
     exactly like the text layer.
  5. Measure the composite's loudness (no -v error: the Parsed_loudnorm
     JSON prints at INFO level and -v error suppresses it).
  6. Cinema finish, in the final encode: hqdn3d denoise, eq grade,
     colorbalance (warm highlights / cool shadows), unsharp, vignette,
     film grain noise=alls=7, fade-out in the last 0.5s only (NO fade-in).
     Two-pass loudnorm to -23 LUFS (TP -2, LRA 11): apply with the
     measured values and linear=true. libx264 CRF 15, preset slow,
     1080x1920, 24 fps, maxrate 20M, yuv420p, faststart.
  7. Verify: 1080x1920, 24 fps, duration within 0.5s of the
     segment timeline total (last word + 0.5s tail), loudness
     within 0.5 LUFS of -23. Fail loudly on any mismatch.

There is NO size cap. Echoes finals are 180-310 MB; the old assemble.py
failed anything over 100 MB. That cap is gone.
"""
import argparse
import json
import os
import re
import subprocess
import sys

# kenburns_v2 lives in this same directory; import it by path (the
# package name has a hyphen, so a normal package import is not valid
# syntax — and this keeps the script runnable directly as well as via
# `python3 -m pipeline-v2.render.echoes_assemble_v2`). kenburns_v2
# imports cv2/numpy lazily inside its render function, so this import
# never fails on a machine without OpenCV.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kenburns_v2


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
    fmt = d.get("format", {})
    # Still images (notably .webp) carry no format.duration — ffprobe
    # omits the key entirely (67 Gate 4: KeyError 'duration' on the
    # first PLAIN .webp still). Duration is only used for video clips
    # and the finished file, both of which always carry it; a still
    # reports None and its callers never touch the field.
    try:
        duration = float(fmt["duration"])
    except (KeyError, TypeError, ValueError):
        duration = None
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": int(num) / int(den),
        "duration": duration,
        "size": int(fmt["size"]),
    }


def probe_frames(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames",
         "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def last_full_opacity_frame(captions_json, caption_video):
    """Frame index of the last FULL-OPACITY frame of the caption layers.

    The builder fades the last caption group out over exit_dur =
    min(0.12, (end - start) * 0.3) ending at the group's end, so the
    caption video's final frames are already faded — tpad-cloning the
    video's last frame would freeze a faded caption (the 64 Gate 3 v1
    defect). The last full-opacity frame is at (last_end - exit_dur).
    """
    with open(captions_json) as f:
        groups = json.load(f)
    last = groups[-1]
    end = float(last["end"])
    start = float(last["start"])
    exit_dur = min(0.12, (end - start) * 0.3)
    # The fade starts at (end - exit_dur), which usually falls INSIDE a
    # frame. The last FULLY-opaque frame is the last frame whose END is
    # at or before the fade start: int((end - exit_dur) * 24) - 1.
    # (64: last group 76.22-77.36, exit_dur 0.12, fade starts 77.24s =
    # inside frame 1853, so the last full-opacity frame is 1852. The
    # local v3 used 1853 — one frame later, ~92% opaque at the fade's
    # start, verified frozen by the red team; the difference is
    # immaterial, and 1852 is the strictly fully-opaque frame.)
    frame = int((end - exit_dur) * 24) - 1
    total_frames = probe_frames(caption_video)
    if frame >= total_frames:
        raise SystemExit(
            f"last full-opacity frame {frame} >= caption video frames "
            f"{total_frames} — caption video shorter than the JSON says")
    return frame


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


def last_frame_luma(path):
    """Mean RGB luma (Rec.601) of the final frame of a video file.

    Tail-fade assertion (65 Gate 4 F1, 2026-11-20): the 0.5s fade-out
    must complete, so the final frame must be near black. Run
    44742850858 applied fade=t=out:st=64.000:d=0.5 correctly (confirmed
    from its assemble job log) yet shipped a final frame at mean luma
    18.38 — the fade ran at half rate on that runner. The 63 v2 control
    measured 5.68 by this same method. Threshold 10 sits between the
    passing control and the failing render.
    """
    n = probe_frames(path)
    info = probe(path)
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path,
         "-vf", f"select='eq(n,{n - 1})'",
         "-frames:v", "1", "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True)
    raw = out.stdout
    expected = info["width"] * info["height"] * 3
    if len(raw) != expected:
        raise RuntimeError(
            f"last-frame extraction gave {len(raw)} bytes, expected "
            f"{expected} — cannot measure tail fade")
    pixels = len(raw) // 3
    return (0.299 * sum(raw[0::3]) + 0.587 * sum(raw[1::3])
            + 0.114 * sum(raw[2::3])) / pixels


def blur_fill_filter(width, height):
    """Blur-fill a (usually landscape) clip into 1080x1920."""
    fg_h = round(1080 * height / width)
    fg_y = (1920 - fg_h) // 2
    return (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,gblur=sigma=40,eq=brightness=-0.25[bg];"
        f"[0:v]scale=1080:{fg_h}[fg];"
        f"[bg][fg]overlay=(W-w)/2:{fg_y},format=yuv420p"
    )


def concat_segments(trimmed, out):
    """Join the encoded segments with the concat FILTER (re-encode).

    NOT "-f concat -c copy": the concat demuxer fills timestamp gaps
    between files by duplicating frames (local ffmpeg 8.1.2 turned
    465 segment frames into a 466-frame concat) or drops frames
    (GitHub ffmpeg 6.1.1 turned the same chain into 463) — the frame
    count is version-dependent. The concat filter passes the frame
    streams through, so the total is exactly the sum of the segment
    frames on any ffmpeg version. All segments are 1080x1920
    yuv420p 24 fps by construction, so the filter takes them directly.
    """
    inputs = []
    for p in trimmed:
        inputs += ["-i", p]
    filt = "".join(f"[{k}:v]" for k in range(len(trimmed)))
    filt += (f"concat=n={len(trimmed)}:v=1:a=0,"
             "format=yuv420p[v]")
    run(["ffmpeg", "-y", "-v", "error", *inputs,
         "-filter_complex", filt, "-map", "[v]",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-r", "24", "-an", out])


def main():
    parser = argparse.ArgumentParser(
        description="assemble an Echoes short from locked clips")
    parser.add_argument("--segments-dir", required=True)
    parser.add_argument("--segment-map", required=True)
    parser.add_argument("--captions", required=False, default=None,
                        help="captions-24fps.mp4 (HyperFrames, 24 fps); "
                             "omit for a caption-free render")
    parser.add_argument("--captions-plates", required=False, default=None,
                        help="captions-plates-24fps.mp4 (Hormozi only); "
                             "multiplied onto the footage before the text "
                             "layer is screened on top; omit for legacy "
                             "captions (no plates file exists)")
    parser.add_argument("--captions-json", required=False, default=None,
                        help="captions.json (Hormozi groups): needed to "
                             "find the last full-opacity frame for the "
                             "tail freeze (G1); required when --captions "
                             "is given")
    parser.add_argument("--audio", required=True, help="narration mix wav")
    parser.add_argument("--out", required=True)
    parser.add_argument("--work-dir", default="work/assemble")
    parser.add_argument("--verify-only", action="store_true",
                        help="run the input checks only (segment files "
                             "exist, durations vs windows incl. the G5 "
                             "hold refusal, frame-pinned concat vs mix, "
                             "captions JSON vs layers) and exit without "
                             "encoding anything — Gate 4 pre-flight for "
                             "71+ (the local cinema twin was retired "
                             "after 70)")
    args = parser.parse_args()

    if args.captions and not args.captions_json:
        raise SystemExit("--captions given without --captions-json: the "
                         "tail freeze needs the JSON to find the last "
                         "full-opacity frame (G1)")
    if args.captions_plates and not args.captions:
        raise SystemExit("--captions-plates given without --captions: "
                         "plates need the caption text layer")
    if args.captions_plates and not os.path.exists(args.captions_plates):
        raise SystemExit(f"--captions-plates file not found: "
                         f"{args.captions_plates} (legacy captions produce "
                         f"no plates file — omit the argument instead)")

    # The final encode writes to --out (usually out/<final>.mp4). When the
    # captions job is skipped there is no captions artifact download to
    # create out/ first, so make it here — otherwise ffmpeg fails with
    # "Error opening output ... No such file or directory" at the finish.
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

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

    if args.verify_only:
        # VERIFY-ONLY (Gate 4 pre-flight for 71+, Hub correction
        # 2026-11-19): run every input check the encode path
        # enforces, without encoding anything. The local cinema twin
        # was a duplicate render — 70 is the LAST video that gets
        # one. A failure here is the same failure the encode would
        # hit, caught before any segment is rendered (the B7b 0.513s
        # hold refusal on 70 is the case this exists for).
        if abs(total - mix_dur) > 1.0:
            raise SystemExit(
                f"verify-only: segment timeline {total:.2f}s and mix "
                f"{mix_dur:.2f}s differ by more than 1s")
        concat_frames = 0
        for i, seg in enumerate(segments):
            src = os.path.join(args.segments_dir, seg["file"])
            if not os.path.exists(src):
                raise SystemExit(
                    f"verify-only: segment {i} file not found: {src}")
            dur = float(seg["end"]) - float(seg["start"])
            if dur <= 0:
                raise SystemExit(
                    f"verify-only: segment {i} ({seg['file']}): "
                    f"bad duration {dur}")
            concat_frames += max(1, round(dur * 24))
            if seg.get("kenburns") is not None:
                # KEN BURNS (SOLVED): validate the spec (keys + clamp)
                # without rendering — the render happens on the runner.
                if not seg["file"].lower().endswith(
                        (".jpg", ".jpeg", ".png", ".webp")):
                    raise SystemExit(
                        f"verify-only: segment {i} ({seg['file']}): "
                        f"kenburns needs a still image, not "
                        f"{seg['file']}")
                try:
                    vals = kenburns_v2.validate_kenburns_spec(
                        seg["kenburns"])
                except ValueError as e:
                    raise SystemExit(
                        f"verify-only: segment {i} ({seg['file']}): "
                        f"invalid kenburns spec: {e}")
                print(f"verify-only: segment {i}: kenburns "
                      f"{seg['file']} {dur:.3f}s zoom "
                      f"{vals['zoom0']}->{vals['zoom1']}")
                continue
            if seg["file"].lower().endswith(
                    (".jpg", ".jpeg", ".png", ".webp")):
                print(f"verify-only: segment {i}: still beat "
                      f"{seg['file']} held {dur:.3f}s")
                continue
            info = probe(src)
            if dur - info["duration"] > 1 / 24:
                raise SystemExit(
                    f"verify-only: segment {i} ({seg['file']}): segment "
                    f"{dur:.3f}s is {dur - info['duration']:.3f}s LONGER "
                    f"than its clip ({info['duration']:.2f}s) — re-type "
                    f"as a still beat or re-cut; no silent hold")
        concat_dur = concat_frames / 24
        print(f"verify-only: concat {concat_dur:.2f}s "
              f"({concat_frames} frames) vs mix {mix_dur:.2f}s")
        if concat_dur < mix_dur:
            shortfall = mix_dur - concat_dur
            if shortfall > 0.05:
                raise SystemExit(
                    f"verify-only: CONCAT TOO SHORT — short by "
                    f"{shortfall:.2f}s; quantisation explains at most 0.05s")
            print(f"verify-only: concat short by {shortfall:.2f}s "
                  f"(within the 0.05s pad)")
        if args.captions:
            last_full = last_full_opacity_frame(args.captions_json,
                                                args.captions)
            print(f"verify-only: captions last full-opacity frame "
                  f"{last_full}")
            if args.captions_plates:
                last_full_p = last_full_opacity_frame(
                    args.captions_json, args.captions_plates)
                print(f"verify-only: plates last full-opacity frame "
                      f"{last_full_p}")
        print("verify-only: PASS")
        return 0

    os.makedirs(args.work_dir, exist_ok=True)
    trimmed = []
    for i, seg in enumerate(segments):
        src = os.path.join(args.segments_dir, seg["file"])
        dur = float(seg["end"]) - float(seg["start"])
        if dur <= 0:
            raise SystemExit(f"segment {i} ({seg['file']}): bad duration {dur}")
        # FRAME-PIN: the encode's frame count is pinned, not left to
        # "-t" + fps boundary rounding (see module docstring).
        nframes = max(1, round(dur * 24))
        if seg.get("kenburns") is not None:
            # KEN BURNS (SOLVED 2026-11-19): render the move on the
            # runner with kenburns_v2.py (OpenCV subpixel warp — the
            # PROVEN prototype). Never ffmpeg zoompan (vibrates on
            # fine detail, 58 Gap1). Anything this step cannot render
            # fails loudly here — never a still or a zoompan
            # substituted silently. The rendered mp4 is already
            # 1080x1920/24fps/yuv420p, so it bypasses the blur-fill
            # re-encode (the concat filter re-encodes anyway).
            if not seg["file"].lower().endswith(
                    (".jpg", ".jpeg", ".png", ".webp")):
                raise SystemExit(
                    f"segment {i} ({seg['file']}): kenburns needs a "
                    f"still image, not {seg['file']}")
            try:
                vals = kenburns_v2.validate_kenburns_spec(
                    seg["kenburns"])
            except ValueError as e:
                raise SystemExit(
                    f"segment {i} ({seg['file']}): invalid kenburns "
                    f"spec: {e}")
            out = os.path.join(args.work_dir, f"seg{i:02d}.mp4")
            kenburns_v2.render_kenburns(src, out, dur, vals)
            got = probe_frames(out)
            if got != nframes:
                raise SystemExit(
                    f"segment {i} ({seg['file']}): kenburns rendered "
                    f"{got} frames, expected {nframes} — frame pin failed")
            print(f"segment {i}: kenburns {seg['file']} {dur:.3f}s "
                  f"zoom {vals['zoom0']}->{vals['zoom1']}")
            trimmed.append(out)
            continue
        if seg["file"].lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            # STILL BEAT (G3): a locked still held for the segment
            # duration. Loop the still; no motion is faked here.
            out = os.path.join(args.work_dir, f"seg{i:02d}.mp4")
            info = probe(src)
            run(["ffmpeg", "-y", "-v", "error",
                 "-loop", "1", "-framerate", "24", "-i", src,
                 "-frames:v", str(nframes),
                 "-filter_complex", blur_fill_filter(info["width"], info["height"]),
                 "-r", "24", "-an",
                 "-c:v", "libx264", "-crf", "18", "-preset", "medium", out])
            got = probe_frames(out)
            if got != nframes:
                raise SystemExit(
                    f"segment {i} ({seg['file']}): still beat encoded "
                    f"{got} frames, expected {nframes} — frame pin failed")
            print(f"segment {i}: still beat {seg['file']} held {dur:.3f}s")
            trimmed.append(out)
            continue
        info = probe(src)
        out = os.path.join(args.work_dir, f"seg{i:02d}.mp4")
        if dur - info["duration"] > 1 / 24:
            # NO SILENT HOLDS (G5): a segment longer than its clip is a
            # planning defect, not something to paper over with a held
            # last frame. The local method bans unplanned holds; a fill
            # of <=1s must be ruled as a fill at review, anything
            # longer re-typed as a still beat. Fail loudly here.
            # One frame of tolerance: timeline times are decimal seconds
            # while a clip holds whole frames (213f is 8.875s against
            # an 8.88s window) — the trim takes the frames that exist
            # and the concat shortfall pad absorbs the sub-frame gap.
            raise SystemExit(
                f"segment {i} ({seg['file']}): segment {dur:.3f}s is "
                f"{dur - info['duration']:.3f}s LONGER than its clip "
                f"({info['duration']:.2f}s) — re-type as a still beat "
                f"or re-cut; no silent hold")
        # Trim from the START of this clip, for the segment duration.
        # -frames:v pins the count (see module docstring); -t does not.
        src_frames = probe_frames(src)
        run(["ffmpeg", "-y", "-v", "error", "-i", src,
             "-frames:v", str(nframes),
             "-filter_complex", blur_fill_filter(info["width"], info["height"]),
             "-r", "24", "-an",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", out])
        got = probe_frames(out)
        expect = min(src_frames, nframes)
        if got > nframes or got < expect - 1:
            raise SystemExit(
                f"segment {i} ({seg['file']}): encoded {got} frames, "
                f"expected {expect} (clip {src_frames}f, window "
                f"{nframes}f) — frame pin failed")
        trimmed.append(out)

    silent = os.path.join(args.work_dir, "silent.mp4")
    concat_segments(trimmed, silent)
    concat_dur = probe(silent)["duration"]
    print(f"concat {concat_dur:.2f}s (mix {mix_dur:.2f}s)")
    if concat_dur < mix_dur:
        # Each segment is encoded at 24 fps, so its duration quantises
        # to whole frames (1/24s = 0.042s). The chain can therefore land
        # a frame or two short of the mix even when the timeline is
        # right — 84 was 0.03s short, 82 was 0.04s short. That is not
        # a real sync problem: hold the last frame of the last segment
        # (same tpad hold used above for clips shorter than their
        # segment) until the chain reaches the mix, then re-concat.
        # A shortfall over 0.05s is still a real problem — stop.
        shortfall = mix_dur - concat_dur
        if shortfall > 0.05:
            # v2 (G5): the v1 code silently padded shortfalls up to
            # 1.0s — a held last frame masking a planning defect.
            # Frame quantisation (1/24s = 0.042s) explains at most
            # ~0.05s; anything more is a real shortfall. Fail.
            raise SystemExit(
                f"CONCAT TOO SHORT — STOP, do not mux a short chain "
                f"(short by {shortfall:.2f}s; quantisation explains "
                f"at most 0.05s)")
        import math
        pad = math.ceil(shortfall * 24) / 24
        last = trimmed[-1]
        padded = os.path.join(args.work_dir, "seg_last_padded.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-i", last,
             "-vf", f"tpad=stop_duration={pad:.3f}:stop_mode=clone",
             "-r", "24", "-an",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", padded])
        trimmed[-1] = padded
        concat_segments(trimmed, silent)
        concat_dur = probe(silent)["duration"]
        print(f"concat padded +{pad:.3f}s -> {concat_dur:.2f}s "
              f"(mix {mix_dur:.2f}s)")
        if concat_dur < mix_dur:
            raise SystemExit("CONCAT STILL TOO SHORT after padding — STOP")

    # MUX + AUDIO PAD (69 Gate 4 Defect 2 fix): the video chain IS the
    # final length — the timeline total is the last word + 0.5s by
    # construction, so the concat already runs 0.5s past the last
    # word. NO -shortest (it would cut the video to the mix), NO
    # tpad (it would freeze the last frame under the fade). The
    # audio is padded with silence to the video length instead:
    # the mix ends 0.2s after the last word and apad adds the rest,
    # so the tail is ~0.5s of MOVING video under the fade.
    with_audio = os.path.join(args.work_dir, "with_audio.mp4")
    run(["ffmpeg", "-y", "-v", "error",
         "-i", silent, "-i", args.audio,
         "-filter_complex",
         f"[1:a]apad=whole_dur={concat_dur:.3f}[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-frames:v", str(probe_frames(silent)),
         with_audio])

    # The muxed file IS the tailed file now: video 2181f, audio
    # padded to the same length, no cloned frames anywhere.
    tailed = with_audio
    tailed_dur = probe(tailed)["duration"]

    composited = os.path.join(args.work_dir, "composite.mp4")
    if args.captions:
        # TAIL FREEZE (G1, 64 Gate 3 v1 defect): the caption layers
        # are PRE-EXTENDED as standalone files — trim at the last
        # full-opacity frame, tpad-clone to the tailed length, frame
        # count verified — BEFORE compositing. The composite graph
        # carries NO trim/tpad: tpad inside the composite graph does
        # NOT take effect, and cloning the caption video's last frame
        # would freeze an already-faded caption anyway (the builder
        # fades the last group out over exit_dur at its end).
        tailed_frames = int(round(tailed_dur * 24))
        last_full = last_full_opacity_frame(args.captions_json, args.captions)
        text_ext = os.path.join(args.work_dir, "text-extended.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-i", args.captions,
             "-vf", f"trim=end_frame={last_full + 1},"
                    f"tpad=stop={tailed_frames - last_full - 1}:stop_mode=clone,"
                    "format=yuv420p",
             "-frames:v", str(tailed_frames), "-an",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", text_ext])
        if probe_frames(text_ext) != tailed_frames:
            raise SystemExit(
                f"extended text layer is {probe_frames(text_ext)} frames, "
                f"expected {tailed_frames} — tail freeze failed")
        print(f"tail freeze: text layer frozen from frame {last_full} "
              f"to {tailed_frames} frames")
        plate_ext = None
        if args.captions_plates:
            plate_ext = os.path.join(args.work_dir, "plate-extended.mp4")
            run(["ffmpeg", "-y", "-v", "error", "-i", args.captions_plates,
                 "-vf", f"trim=end_frame={last_full + 1},"
                        f"tpad=stop={tailed_frames - last_full - 1}:stop_mode=clone,"
                        "format=yuv420p",
                 "-frames:v", str(tailed_frames), "-an",
                 "-c:v", "libx264", "-crf", "18", "-preset", "medium", plate_ext])
            if probe_frames(plate_ext) != tailed_frames:
                raise SystemExit(
                    f"extended plate layer is {probe_frames(plate_ext)} "
                    f"frames, expected {tailed_frames} — tail freeze failed")
        inputs = ["-i", tailed, "-i", text_ext]
        fc = "[0:v]format=gbrp[v0];[1:v]format=gbrp[cap2];"
        if plate_ext:
            # Hormozi plates: white background, dark per-word plates.
            # Multiply first (white disappears, footage darkens under
            # each plate), then screen the text on top.
            inputs += ["-i", plate_ext]
            fc += ("[2:v]format=gbrp[plate2];"
                   "[v0][plate2]blend=all_mode=multiply[vm];"
                   "[vm][cap2]blend=all_mode=screen,format=yuv420p[v]")
            print(f"compositing plates {args.captions_plates} under captions")
        else:
            fc += ("[v0][cap2]blend=all_mode=screen,"
                   "format=yuv420p[v]")
        run(["ffmpeg", "-y", "-v", "error", *inputs,
             "-filter_complex", fc,
             "-map", "[v]", "-map", "0:a",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium",
             "-c:a", "copy", "-r", "24", composited])
    else:
        # Caption-free render: the tailed chain IS the composite.
        # No overlay, no captions video needed.
        print("no --captions: caption-free render, skipping overlay")
        run(["ffmpeg", "-y", "-v", "error", "-i", tailed,
             "-c", "copy", composited])

    # Two-pass loudnorm: measure, then finish with measured values.
    measured = measure_loudness(composited)
    print("loudnorm measured:", json.dumps(measured))
    # G4: the v1 finish used the PRE-FIX 58 grade (brightness 0.02,
    # vignette PI/5 — red-team failed as too dark, mean -18.6 luma vs
    # the base). Current local finish: brightness 0.06, vignette PI/7
    # (whole video, no tail exclusion — the 68 v1 lesson), hqdn3d
    # 4:4:6:6, unsharp 0.6, grain alls=7:allf=t+u.
    video_filter = (
        "hqdn3d=4:4:6:6,eq=contrast=1.10:saturation=1.18:brightness=0.06,"
        "colorbalance=gs=-0.04:bs=0.06:rh=0.04:gh=0.01,"
        "unsharp=5:5:0.6:5:5:0.0,vignette=PI/7,"
        "noise=alls=7:allf=t+u,"
        f"fade=t=out:st={(tailed_frames - 1) / 24 - 0.5:.3f}:d=0.5,format=yuv420p"  # last 0.5s of the VIDEO, ending on the LAST FRAME ((tailed_frames-1)/24): the old st=tailed_dur-0.5 ended the fade 1/24s past the last frame, so the last frame sat 8.3% into the fade and a bright last frame failed the luma assertion (66 Gate 4: luma 13.62)
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
    if abs(info["duration"] - total) > 0.5:
        errors.append(f"duration {info['duration']:.2f}s != "
                      f"expected timeline total {total:.2f}s")
    final_loudness = measure_loudness(args.out)
    print("final loudness:", json.dumps(final_loudness))
    if abs(float(final_loudness["input_i"]) - (-23)) > 0.5:
        errors.append(f"loudness {final_loudness['input_i']} LUFS != -23")
    # Last-frame luma assertion (65 Gate 4 F1): the 0.5s tail fade must
    # complete — the final frame must be near black (< 10 mean RGB luma;
    # 63 v2 measured 5.68, the failed 65 v1 measured 18.38). A correct
    # fade filter can still render at half rate on a runner, so the
    # render must fail loudly here instead of shipping mid-fade.
    last_luma = last_frame_luma(args.out)
    print(f"last-frame mean RGB luma: {last_luma:.2f}")
    if last_luma >= 10:
        errors.append(f"last-frame luma {last_luma:.2f} >= 10 — "
                      "tail fade did not complete")
    if errors:
        for e in errors:
            print("VERIFY FAILED: " + e, file=sys.stderr)
        return 1
    print("verify passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
