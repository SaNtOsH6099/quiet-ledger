#!/usr/bin/env python3
"""Infinite-zoom beat transition (Echoes Originals prototype).

DaVinci Fusion "invisible zoom" equivalent, OpenCV only, no zoompan:
  still/clip A full frame -> still/clip B stacked tiny inside a portal
  point in A -> B scales up until it fills the frame -> hold / play B.

Geometry (documented choice):
  scale s(t) = 0.05 * 20**u, u = smoothstep(i / (Nzoom-1)) — geometric
  growth, slow start, fast middle, gentle settle. s goes 0.05 -> 1.0.
  B centre eases from the portal point to the frame centre over the
  same u. A portal-locked centre would end cropped (portal x=0.20 needs
  1.6x to cover the frame); easing the centre lets the zoom settle on
  the full composed B frame, so the last zoom frame IS B (MAD ~ 0) and
  the hold / clip handoff is seamless. The portal is honoured where the
  eye reads it: at the start, when B is tiny.
  Feather: B's alpha mask is blurred with a Gaussian whose radius is
  0.0283 * frame width * s (Fusion Soft Edge 0.0283 equivalent, scaled
  with B so a tiny B is not washed out). No rectangle edge is visible.

Pipeline per case (24 fps, 1080x1920, yuv420p, libx264 CRF 18, -an):
  hold A 2.0s (48f) | zoom 2.5s (60f) | hold B 2.0s (48f)  -> 156f, 6.5s
  still->clip: hold B is replaced by clip B frames 0..47 (2.0s).
  clip->still: hold A is replaced by clip A frames 0..47 (2.0s), and the
    zoom base is clip A frame 48 (t=2.00s, the next frame after the
    played segment) frozen.
  clip->clip: both of the above.
Frames are piped to ffmpeg (libx264, -r 24 output pinning). No zoompan
anywhere. Stills are 1152x2048 -> resized 1080x1920 INTER_CUBIC; clips
are 704x1248 -> resized 1080x1920 INTER_CUBIC (softer than a still,
noted in QC).

Usage:
  python3 infinite_zoom.py --spec cases/case1.json --out out.mp4
Spec JSON fields: case, mode, a_still/a_clip, b_still/b_clip,
portal_x, portal_y (0-1 in the 1080x1920 frame), a_clip_frames,
b_clip_frames (first N frames of the clip to play), hold_a_s, zoom_s,
hold_b_s. Paths are relative to the staging dir passed with --in-dir.
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


def load_clip_frames(path, indices):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open clip: {path}")
    want = set(indices)
    out = {}
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if n in want:
            out[n] = cv2.resize(frame, (W, H), interpolation=cv2.INTER_CUBIC)
            if len(out) == len(want):
                break
        n += 1
    cap.release()
    missing = [i for i in indices if i not in out]
    if missing:
        raise SystemExit(f"clip {path} missing frames {missing}")
    return [out[i] for i in indices]


def smoothstep(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def zoom_frame(base, b_img, portal, i, n_zoom):
    """One zoom frame: B scaled/centred over base, feathered alpha."""
    u = smoothstep(i / (n_zoom - 1))
    s = 0.05 * (20.0 ** u)
    cx = portal[0] + (W / 2 - portal[0]) * u
    cy = portal[1] + (H / 2 - portal[1]) * u
    bw, bh = max(2, int(round(W * s))), max(2, int(round(H * s)))
    small = cv2.resize(b_img, (bw, bh), interpolation=cv2.INTER_CUBIC)
    x0 = int(round(cx - bw / 2))
    y0 = int(round(cy - bh / 2))
    # Feathered alpha mask, full frame, blurred at 0.0283 * width * s.
    feather = max(2, int(round(0.0283 * W * s)))
    k = feather * 2 + 1
    mask = np.zeros((H, W), dtype=np.float32)
    mx0, my0 = max(0, x0), max(0, y0)
    mx1, my1 = min(W, x0 + bw), min(H, y0 + bh)
    if mx1 > mx0 and my1 > my0:
        mask[my0:my1, mx0:mx1] = 1.0
    # BORDER_REPLICATE: a full-frame mask stays 1.0 at s=1 (no rim blend).
    mask = cv2.GaussianBlur(mask, (k, k), 0, borderType=cv2.BORDER_REPLICATE)
    # Composite B over base where they overlap.
    out = base.astype(np.float32)
    bx0, by0 = mx0 - x0, my0 - y0
    region = small[by0:by0 + (my1 - my0), bx0:bx0 + (mx1 - mx0)].astype(np.float32)
    a = mask[my0:my1, mx0:mx1][:, :, None]
    out[my0:my1, mx0:mx1] = region * a + out[my0:my1, mx0:mx1] * (1.0 - a)
    return np.clip(out, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--in-dir", default="in")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.spec) as f:
        spec = json.load(f)
    portal = (spec["portal_x"] * W, spec["portal_y"] * H)
    n_hold_a = int(round(spec["hold_a_s"] * FPS))
    n_zoom = int(round(spec["zoom_s"] * FPS))
    n_hold_b = int(round(spec["hold_b_s"] * FPS))

    # --- A side ---
    if "a_clip" in spec:
        a_frames = load_clip_frames(os.path.join(args.in_dir, spec["a_clip"]),
                                    list(range(spec["a_clip_frames"])))
        freeze_idx = spec["a_clip_frames"]  # frame 48, t = 2.00s
        a_base = load_clip_frames(os.path.join(args.in_dir, spec["a_clip"]),
                                  [freeze_idx])[0]
        head = a_frames
    else:
        a_base = load_image(os.path.join(args.in_dir, spec["a_still"]))
        head = [a_base] * n_hold_a

    # --- B side ---
    if "b_clip" in spec:
        b_img = load_clip_frames(os.path.join(args.in_dir, spec["b_clip"]),
                                 [0])[0]
        # B zoom still is clip B frame 0 itself, so the handoff is exact.
        tail = load_clip_frames(os.path.join(args.in_dir, spec["b_clip"]),
                                list(range(spec["b_clip_frames"])))
    else:
        b_img = load_image(os.path.join(args.in_dir, spec["b_still"]))
        tail = [b_img] * n_hold_b

    total = len(head) + n_zoom + len(tail)
    print(f"case {spec['case']} mode={spec['mode']} frames={total} "
          f"({total / FPS:.2f}s) portal={spec['portal_x']},{spec['portal_y']}",
          flush=True)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-crf", "18", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fr in head:
        proc.stdin.write(fr.tobytes())
    for i in range(n_zoom):
        proc.stdin.write(zoom_frame(a_base, b_img, portal, i, n_zoom).tobytes())
    for fr in tail:
        proc.stdin.write(fr.tobytes())
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"ffmpeg failed rc={rc}")
    print(f"wrote {args.out} frames={total}", flush=True)


if __name__ == "__main__":
    main()
