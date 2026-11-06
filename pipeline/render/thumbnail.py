#!/usr/bin/env python3
"""Draw the thumbnail in code: 1280x720, paper background, big bold title.

The title comes from the draft (the hook lines of the first beat, or the
topic). No photos, no generated imagery. Uses DejaVu Sans Bold, which is
present on the runner image; falls back to Pillow's default font.
"""
import argparse
import json
import textwrap

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
BG = (246, 241, 231)
INK = (28, 28, 28)
RED = (217, 72, 31)
GREY = (138, 131, 120)


def load_font(size, bold=True):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_thumbnail(title, eyebrow, out_path):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    # faint dotted paper texture
    for x in range(14, W, 28):
        for y in range(14, H, 28):
            draw.ellipse([x, y, x + 2, y + 2], fill=(232, 228, 220))
    # red rule above the title
    draw.rectangle([80, 118, 200, 130], fill=RED)
    eyebrow_font = load_font(44, bold=True)
    draw.text((80, 150), eyebrow.upper(), font=eyebrow_font, fill=GREY)
    # title, wrapped to fit, big bold
    font = load_font(118, bold=True)
    lines = []
    for chunk in title.upper().split("\n"):
        lines.extend(textwrap.wrap(chunk, width=14))
    lines = lines[:3]
    y = 250
    for line in lines:
        draw.text((76, y), line, font=font, fill=INK)
        y += 128
    # red underline swoosh under the last line
    draw.line([80, y + 6, 80 + 340, y + 6], fill=RED, width=10)
    img.save(out_path)
    print(f"wrote {out_path}: {W}x{H}")


def title_from_script(script_obj):
    """Prefer the hook lines of the first beat, else the topic."""
    beats = script_obj.get("beats", [])
    if beats and beats[0].get("type") == "kinetic":
        lines = beats[0].get("data", {}).get("lines", [])
        text = "\n".join(line.get("text", "") for line in lines)
        if text.strip():
            return text
    return script_obj.get("topic", "A STRANGE FACT")


def main():
    parser = argparse.ArgumentParser(description="draw the thumbnail")
    parser.add_argument("--script", required=True,
                        help="script.json (submitted by Muse)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--eyebrow", default="A strange fact")
    args = parser.parse_args()
    obj = json.load(open(args.script))
    draw_thumbnail(title_from_script(obj), args.eyebrow, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
