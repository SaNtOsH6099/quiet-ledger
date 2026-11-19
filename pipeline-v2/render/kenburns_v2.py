#!/usr/bin/env python3
"""Ken Burns renderer for the Echoes v2 GitHub pipeline (SOLVED 2026-11-19).

Renders a Ken Burns segment on the runner from a still image + a numeric
spec, instead of requiring a pre-rendered mp4. Ported from the PROVEN
local prototype (~/workspace/github-v2-render-draft/work/kenburns-proto/
kenburns.py + REPORT.md): upscale the still 2x (INTER_CUBIC), then per
output frame a FLOAT affine map (scale + translate) via
cv2.warpAffine(..., INTER_LINEAR | WARP_INVERSE_MAP, BORDER_REPLICATE),
zoom/centre linear in time (constant velocity). Pipe raw BGR frames to
ffmpeg: libx264, yuv420p, -r 24, CRF 18, 1080x1920, +faststart.

Method rules (lessons file ~/workspace/user/files/echoes-clip-lessons.md):
  lesson 40 (recipe): one direction only, zoom 1.00-1.20 (8-20%), centre
    = the subject the narration names, as fractions of the still.
  lesson 50 (clamp): end centres MUST stay inside 1/(2z) <= c <= 1-1/(2z)
    for the end zoom z — outside the bound the crop window runs out of
    the still and BORDER_REPLICATE smears a stripe down the edge.
    Enforced here by an assert in validate_kenburns_spec; the last
    frame is still checked by eye at review (MAD does not catch smears).
  lesson 46: NO fps filter anywhere in a GitHub-rendered path (ffmpeg
    6.1.1 drops the last frame under fps=24); the rate is pinned by
    "-r 24" on the ffmpeg output, never a filter.
  lesson 85: all rendering on GitHub — this module is what lets KB
    segments render on the runner instead of locally.

The ONLY banned implementation remains ffmpeg zoompan (integer-pixel
crop steps vibrate on fine detail, 58 Gap1). This module never calls
it, and echoes_assemble_v2.py fails loudly rather than substituting
a still or a zoompan for anything this module cannot render.

Usage as a library (echoes_assemble_v2.py):
    spec = validate_kenburns_spec(seg["kenburns"])   # raises ValueError
    render_kenburns(image, out, dur, spec)          # needs cv2 + ffmpeg

Usage standalone:
    kenburns_v2.py --image still.jpg --out seg.mp4 --dur 6 \
        --zoom0 1.08 --zoom1 1.18 --cx0 0.52 --cy0 0.48 --cx1 0.48 --cy1 0.52

cv2/numpy are imported lazily inside render_kenburns so that importing
this module (e.g. for spec validation in --verify-only) never fails on
a machine without OpenCV. The workflow pip-installs
opencv-python-headless==5.1.0.95 + numpy==2.5.5 (the prototype-proven
pair) in the assemble job before echoes_assemble_v2.py runs.
"""
import argparse
import subprocess
import sys

OUT_W, OUT_H = 1080, 1920
FPS = 24
ZOOM_MIN, ZOOM_MAX = 1.0, 1.20
OVERSAMPLE = 2.0
CRF = 18
# Warn (do not fail) when a centre sits this close to the clamp edge:
# 70's B3b end centre cy 0.545 against a 0.5455 limit passed only
# because the last frame was clean (lesson 50).
CLAMP_MARGIN_WARN = 0.01

SPEC_KEYS = ("zoom0", "zoom1", "cx0", "cy0", "cx1", "cy1")


def _clamp_bounds(zoom):
    """(lo, hi) for a centre fraction at this zoom (lesson 50)."""
    lo = 1.0 / (2.0 * zoom)
    return lo, 1.0 - lo


def validate_kenburns_spec(spec):
    """Validate a kenburns segment spec; return a normalised dict of floats.

    Raises ValueError with the exact violation. The assemble step calls
    this BEFORE rendering (and --verify-only calls it without rendering),
    so a bad spec fails loudly on the runner instead of producing a
    smeared or frozen segment. Never silently clamps or substitutes.
    """
    if isinstance(spec, str):
        raise ValueError(
            f"kenburns spec is a string ({spec!r}) — the old form is not "
            f"renderable. Supply the numeric spec: "
            f'{{"zoom0": 1.0, "zoom1": 1.12, "cx0": 0.5, "cy0": 0.5, '
            f'"cx1": 0.5, "cy1": 0.5}}')
    if not isinstance(spec, dict):
        raise ValueError(
            f"kenburns spec must be a dict {SPEC_KEYS}, got "
            f"{type(spec).__name__}: {spec!r}")
    missing = [k for k in SPEC_KEYS if k not in spec]
    if missing:
        raise ValueError(
            f"kenburns spec is missing keys {missing} — required: "
            f"{list(SPEC_KEYS)}")
    vals = {}
    for k in SPEC_KEYS:
        try:
            vals[k] = float(spec[k])
        except (TypeError, ValueError):
            raise ValueError(
                f"kenburns spec key {k!r} is not a number: {spec[k]!r}")
    for k in ("zoom0", "zoom1"):
        if not ZOOM_MIN <= vals[k] <= ZOOM_MAX:
            raise ValueError(
                f"kenburns {k}={vals[k]} outside [{ZOOM_MIN}, {ZOOM_MAX}] "
                f"(method: 1.00-1.20, 8-20% — lesson 40)")
    for k in ("cx0", "cy0", "cx1", "cy1"):
        if not 0.0 <= vals[k] <= 1.0:
            raise ValueError(
                f"kenburns {k}={vals[k]} outside [0, 1] (centre fractions "
                f"of the still)")
    # Lesson-50 clamp, both ends (endpoints suffice: centre is linear in
    # time and the bound 1/(2z) widens as zoom grows, so the tightest
    # point of each side is an endpoint).
    for zkey, ckeys in (("zoom0", ("cx0", "cy0")),
                        ("zoom1", ("cx1", "cy1"))):
        lo, hi = _clamp_bounds(vals[zkey])
        for ck in ckeys:
            c = vals[ck]
            if c < lo - 1e-9 or c > hi + 1e-9:
                raise ValueError(
                    f"kenburns {ck}={c} outside the lesson-50 clamp "
                    f"[{lo:.4f}, {hi:.4f}] at {zkey}={vals[zkey]} — the "
                    f"crop window would run out of the still and "
                    f"BORDER_REPLICATE would smear a stripe down the "
                    f"edge; move the centre inside the bound or raise "
                    f"the zoom")
            # Only warn when the interval is wide enough that a margin
            # can exist: at zoom 1.0 the bound is the single point
            # 0.5, so the (only legal) centre 0.5 is not "near an edge".
            if (hi - lo > 2 * CLAMP_MARGIN_WARN
                    and min(c - lo, hi - c) < CLAMP_MARGIN_WARN):
                print(f"warning: kenburns {ck}={c} is within "
                      f"{CLAMP_MARGIN_WARN} of the clamp edge "
                      f"[{lo:.4f}, {hi:.4f}] at {zkey}={vals[zkey]} — "
                      f"check the last frame by eye (lesson 50)",
                      file=sys.stderr)
    if (vals["zoom0"] == vals["zoom1"] and vals["cx0"] == vals["cx1"]
            and vals["cy0"] == vals["cy1"]):
        raise ValueError(
            "kenburns spec has no movement (zoom and centre constant) — "
            "re-type as a plain still beat, not a Ken Burns segment")
    return vals


def render_kenburns(image, out, dur, spec, ffmpeg="ffmpeg", crf=CRF,
                    fps=FPS, oversample=OVERSAMPLE):
    """Render one Ken Burns segment. spec is a validated spec dict.

    Writes exactly round(dur * fps) frames, 1080x1920, 24 fps, yuv420p,
    libx264 CRF 18. Raises SystemExit on any failure (unreadable still,
    missing cv2/ffmpeg, encoder error) — the caller fails loudly.
    """
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        raise SystemExit(
            "kenburns render needs opencv-python-headless + numpy — "
            "the workflow must pip-install them before the assemble "
            f"step (missing: {e})")
    vals = validate_kenburns_spec(spec)
    src = cv2.imread(image, cv2.IMREAD_COLOR)
    if src is None:
        raise SystemExit(f"kenburns: cannot read still image {image}")
    sh, sw = src.shape[:2]
    # Oversample: working canvas bigger than output so a zoom-in still
    # samples at >= output resolution (avoids upscaling blur at max zoom).
    big = cv2.resize(src, (int(sw * oversample), int(sh * oversample)),
                     interpolation=cv2.INTER_CUBIC)
    bh, bw = big.shape[:2]

    n = int(round(dur * fps))
    if n < 1:
        raise SystemExit(f"kenburns: duration {dur}s gives 0 frames")
    cmd = [ffmpeg, "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{OUT_W}x{OUT_H}", "-r", str(fps), "-i", "-",
           "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-r", str(fps), "-crf", str(crf), "-preset", "medium",
           "-movflags", "+faststart", out]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(n):
            t = i / max(n - 1, 1)          # 0..1 linear progress
            zoom = vals["zoom0"] + (vals["zoom1"] - vals["zoom0"]) * t
            cx = (vals["cx0"] + (vals["cx1"] - vals["cx0"]) * t) * bw
            cy = (vals["cy0"] + (vals["cy1"] - vals["cy0"]) * t) * bh
            # output pixel (ox,oy) <- big-image pixel:
            #   src = centre + (out - out_centre) * (big_w / out_w) / zoom
            # NOTE: warpAffine treats M as src->dst by default and
            # inverts it; pass WARP_INVERSE_MAP so M is used as written
            # (dst->src). The prototype's first renders had this wrong
            # (smeared left band + wrong framing) — do not "fix" it.
            s = (bw / OUT_W) / zoom
            M = np.array([[s, 0, cx - s * OUT_W / 2],
                          [0, s, cy - s * OUT_H / 2]], dtype=np.float64)
            frame = cv2.warpAffine(big, M, (OUT_W, OUT_H),
                                   flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                   borderMode=cv2.BORDER_REPLICATE)
            enc.stdin.write(frame.tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
    if enc.returncode != 0:
        raise SystemExit(f"kenburns: ffmpeg failed rc={enc.returncode}")
    print(f"kenburns: wrote {out}: {n} frames, {dur}s @ {fps}fps, "
          f"zoom {vals['zoom0']}->{vals['zoom1']}, centre "
          f"({vals['cx0']},{vals['cy0']})->({vals['cx1']},{vals['cy1']})")
    return out


def main():
    ap = argparse.ArgumentParser(
        description="render one Ken Burns segment (OpenCV, no zoompan)")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--zoom0", type=float, default=1.0)
    ap.add_argument("--zoom1", type=float, default=1.12)
    ap.add_argument("--cx0", type=float, default=0.5)
    ap.add_argument("--cy0", type=float, default=0.5)
    ap.add_argument("--cx1", type=float, default=0.5)
    ap.add_argument("--cy1", type=float, default=0.5)
    ap.add_argument("--oversample", type=float, default=OVERSAMPLE)
    ap.add_argument("--crf", type=int, default=CRF)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()
    spec = {"zoom0": args.zoom0, "zoom1": args.zoom1,
            "cx0": args.cx0, "cy0": args.cy0,
            "cx1": args.cx1, "cy1": args.cy1}
    try:
        vals = validate_kenburns_spec(spec)
    except ValueError as e:
        raise SystemExit(f"kenburns spec invalid: {e}")
    render_kenburns(args.image, args.out, args.dur, vals,
                    ffmpeg=args.ffmpeg, crf=args.crf,
                    oversample=args.oversample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
