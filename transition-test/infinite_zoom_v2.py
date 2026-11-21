#!/usr/bin/env python3
"""Infinite-zoom v2 — fast lock-in zoom + FULL blend (Case 1 only).

User verdict on v1 (2026-11-21): "no blend, looks very stupid, still
coming from some area inside and become bigger." V1 scaled still B up
as a rectangle over a static A (feather ~0.0283*width*s): mid-zoom
frames show a picture-in-picture rectangle growing in the middle,
centre drifting off the portal, hard edge visible.

V2 is a different mechanism, the user's idea:
  1. Hold A.
  2. FAST lock-in zoom ON A ITSELF toward a measured AREA (not a
     point): A scales up, centre travels from frame centre to the
     area centre, accelerating (ease-in on log scale — slow first
     frame, fast at the end, like a camera punch-in). No B is visible
     during the zoom at all: nothing grows out of anywhere.
  3. FULL BLEND at the peak: 0.5s full-frame cross-dissolve from
     peak-zoom A to B. No rectangle mask, no picture-in-picture, no
     partial blend. A at the peak is soft from upscaling (that
     softness hides the swap — use it, do not sharpen it) plus a
     small motion blur that peaks with zoom speed. B starts slightly
     zoomed in (1.15x) and slightly soft.
  4. Settle on B: B eases out 1.15x -> 1.0x and sharpens, so the
     camera feels like it keeps travelling inside the new scene,
     then hold B.

OpenCV only, no ffmpeg zoompan (banned). 24 fps, 1080x1920, yuv420p,
libx264 CRF 18, -r 24 output pinning.

Usage:
  python3 infinite_zoom_v2.py --spec cases/case1-v2.json --out out.mp4
Spec fields: a_still, b_still, area {x0,y0,x1,y1} normalised 0-1,
fill_scale, hold_a_s, zoom_s, blend_s, settle_s, hold_b_s,
b_settle_scale, blur_peak.
"""
import argparse
import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np

W, H, FPS = 1080, 1920, 24


def load_image(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"cannot read image: {path}")
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_CUBIC)


def crop_zoom(img, cx, cy, scale):
    """Crop a W/scale x H/scale window centred at (cx,cy), resize to full frame.

    BORDER_REPLICATE only if the crop runs off the image edge (it does
    not for the Case 1 area at any scale in the timeline — verified by
    the geometry check in main()).
    """
    cw, ch = W / scale, H / scale
    x0 = int(round(cx - cw / 2))
    y0 = int(round(cy - ch / 2))
    x1 = x0 + int(round(cw))
    y1 = y0 + int(round(ch))
    pad_l = max(0, -x0)
    pad_t = max(0, -y0)
    pad_r = max(0, x1 - W)
    pad_b = max(0, y1 - H)
    crop = img[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
    if pad_l or pad_t or pad_r or pad_b:
        crop = cv2.copyMakeBorder(crop, pad_t, pad_b, pad_l, pad_r,
                                  cv2.BORDER_REPLICATE)
    return cv2.resize(crop, (W, H), interpolation=cv2.INTER_CUBIC)


def blur(img, sigma):
    if sigma <= 0.05:
        return img
    return cv2.GaussianBlur(img, (0, 0), sigma)


def ease_in(u):
    """Accelerating: u^2 on the log-scale exponent. Slow first frame, fast at end."""
    return min(1.0, max(0.0, u)) ** 2


def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--in-dir", default="in")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.spec) as f:
        spec = json.load(f)

    area = spec["area"]  # normalised x0,y0,x1,y1
    ax0, ay0, ax1, ay1 = area["x0"] * W, area["y0"] * H, area["x1"] * W, area["y1"] * H
    acx, acy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
    fill = float(spec["fill_scale"])
    # Geometry check: the crop window at peak zoom must stay inside the image.
    cw, ch = W / fill, H / fill
    assert acx - cw / 2 >= 0 and acx + cw / 2 <= W, "peak crop runs off left/right edge"
    assert acy - ch / 2 >= 0 and acy + ch / 2 <= H, "peak crop runs off top/bottom edge"
    print(f"area bbox px x {ax0:.0f}-{ax1:.0f} y {ay0:.0f}-{ay1:.0f} "
          f"centre ({acx:.0f},{acy:.0f}) fill_scale {fill}", flush=True)

    a_img = load_image(os.path.join(args.in_dir, spec["a_still"]))
    b_img = load_image(os.path.join(args.in_dir, spec["b_still"]))
    blur_peak = float(spec.get("blur_peak", 5.0))
    b_settle_scale = float(spec.get("b_settle_scale", 1.15))

    n_hold_a = int(round(spec["hold_a_s"] * FPS))
    n_zoom = int(round(spec["zoom_s"] * FPS))
    n_blend = int(round(spec["blend_s"] * FPS))
    n_settle = int(round(spec["settle_s"] * FPS))
    n_hold_b = int(round(spec["hold_b_s"] * FPS))
    total = n_hold_a + n_zoom + n_blend + n_settle + n_hold_b
    print(f"v2 timeline: hold_a {n_hold_a}f + zoom {n_zoom}f + blend {n_blend}f "
          f"+ settle {n_settle}f + hold_b {n_hold_b}f = {total}f ({total / FPS:.3f}s)",
          flush=True)

    # Peak-zoom A frame (reused, static, through the whole blend).
    a_peak = blur(crop_zoom(a_img, acx, acy, fill), blur_peak)

    frames = []
    # 1. Hold A.
    frames.extend([a_img] * n_hold_a)
    # 2. Fast lock-in zoom on A. Log-scale, ease-in: s = fill ** ease_in(u).
    for i in range(n_zoom):
        u = i / max(1, n_zoom - 1)
        e = ease_in(u)
        s = fill ** e
        cx = W / 2 + (acx - W / 2) * e
        cy = H / 2 + (acy - H / 2) * e
        # Motion blur grows with zoom speed: ~0 at start, blur_peak at peak.
        # Speed proxy is e itself (accelerating); use sigma = blur_peak * e.
        frames.append(blur(crop_zoom(a_img, cx, cy, s), blur_peak * e))
    # 3. FULL BLEND, full frame, A peak -> B (B starts 1.15x, soft).
    for i in range(n_blend):
        w = (i + 1) / n_blend  # 0..1, linear: a dissolve, not a wipe
        b_frame = blur(crop_zoom(b_img, W / 2, H / 2, b_settle_scale),
                       1.0 + 3.0 * (1.0 - w))
        frames.append(cv2.addWeighted(a_peak, 1.0 - w, b_frame, w, 0))
    # 4. Settle on B: ease out 1.15x -> 1.0x, sharpen 1px -> 0.
    for i in range(n_settle):
        u = smooth(i / max(1, n_settle - 1))
        s = b_settle_scale + (1.0 - b_settle_scale) * u
        frames.append(blur(crop_zoom(b_img, W / 2, H / 2, s), 1.0 * (1.0 - u)))
    # 5. Hold B.
    frames.extend([b_img] * n_hold_b)

    assert len(frames) == total, f"{len(frames)} != {total}"
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-crf", "18", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fr in frames:
        proc.stdin.write(fr.tobytes())
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"ffmpeg failed rc={rc}")
    print(f"wrote {args.out} frames={total}", flush=True)


if __name__ == "__main__":
    main()
