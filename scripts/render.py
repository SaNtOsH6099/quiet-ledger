#!/usr/bin/env python3
"""Draw the scenes: scenes.json data -> HyperFrames composition -> silent frames.

Steps:
  1. Get whisper word timings for the narration (from --words, or by
     running faster-whisper here). Beat boundaries come from the words:
     a beat starts at the first word of its first sentence and ends at
     the last word of its last sentence.
  2. Build a HyperFrames index.html from templates/base.html and one
     component fragment per beat, with the beat data substituted in.
  3. Run `hyperframes check`, then `hyperframes render`. The render is
     silent; narration and captions join it at assembly.
  4. Write out words.json, timings.json (beat boundaries + total length)
     and silent.mp4.

Usage: render.py --scenes script.json --audio narration.wav
         --templates templates --out-dir out --work-dir work/hf
         [--words words.json]
Requires: faster-whisper (only when --words is not given), node + npx.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

W, H = 1080, 1920
# Plot area. x0 leaves 140px on the left so the widest y-axis label
# (e.g. "13.2 °C", ~93px) fits without overflowing the canvas edge;
# the labels sit right-aligned ending at x=140.
PLOT = {"x0": 150, "x1": 970, "y_top": 450, "y_bottom": 1250}


def split_sentences(script):
    parts = re.split(r"(?<=[.!?])\s+", script.strip())
    return [p for p in parts if p]


def sentence_word_counts(sentences):
    return [len(s.split()) for s in sentences]


def beat_boundaries(script, beats, words):
    """Return [(start, end)] per beat, in seconds, from word timings."""
    sentences = split_sentences(script)
    counts = sentence_word_counts(sentences)
    n_script = sum(counts)
    # sentence i starts at this script-word index
    starts = []
    acc = 0
    for c in counts:
        starts.append(acc)
        acc += c

    def word_time(idx):
        """Time of script-word idx, mapped onto whisper words."""
        if not words:
            return 0.0
        if len(words) == n_script:
            w = words[idx]
            return w["s"]
        j = min(len(words) - 1, round(idx * len(words) / max(1, n_script)))
        return words[j]["s"]

    def word_end(idx):
        if not words:
            return 0.0
        if len(words) == n_script:
            return words[idx]["e"]
        j = min(len(words) - 1, round(idx * len(words) / max(1, n_script)))
        return words[j]["e"]

    bounds = []
    for beat in beats:
        idxs = beat["sentences"]
        first_word = starts[idxs[0]]
        last_word = starts[idxs[-1]] + counts[idxs[-1]] - 1
        bounds.append((word_time(first_word), word_end(last_word)))
    return bounds


df build_chart_svg(beat_id, data):
    """Data -> SVG markup for a two-series line chart (one series is fine).
    Returns (svg_string, peak_labels) where peak labels are SVG text."""
    series = data["series"]
    n = len(series[0]["points"])
    xs = [series[0]["points"][i]["x"] for i in range(n)]
    x_of = lambda i: PLOT["x0"] + i * (PLOT["x1"] - PLOT["x0"]) / max(1, n - 1)

    def y_of(s, v):
        vals = [p["y"] for p in s["points"]]
        vmin = min(0, min(vals))
        vmax = max(vals)
        if vmax == vmin:
            vmax = vmin + 1
        return PLOT["y_bottom"] - (v - vmin) / (vmax - vmin) * (
            PLOT["y_bottom"] - PLOT["y_top"]
        )

    def ticks(s):
        vals = [p["y"] for p in s["points"]]
        vmin = min(0, min(vals))
        vmax = max(vals)
        if vmax == vmin:
            vmax = vmin + 1
        return [vmin + (vmax - vmin) * i / 5 for i in range(6)]

    def suffix_for(unit):
        if not unit:
            return ""
        if unit == "deg C":
            return "&deg;"
        return " " + unit

    parts = []
    # gridlines from the first series scale
    grid = ""
    labels_l = ""
    for v in ticks(series[0]):
        y = y_of(series[0], v)
        grid += (f'<line x1="{PLOT["x0"]}" y1="{y:.0f}" '
                 f'x2="{PLOT["x1"]}" y2="{y:.0f}" />\n')
        lab = f"{v:g}"
        labels_l += (f'<text x="140" y="{y + 8:.0f}" text-anchor="end">'
                     f"{lab}{suffix_for(series[0].get('unit', ''))}</text>\n")
    parts.append(f'<g stroke="#d8d0bf" stroke-width="2">\n{grid}</g>')
    parts.append(f'<g class="axis-label">\n{labels_l}</g>')
    # right axis from the second series, if any
    if len(series) > 1:
        labels_r = ""
        for v in ticks(series[1]):
            y = y_of(series[1], v)
            lab = f"{v:g}"
            labels_r += (f'<text x="1070" y="{y + 8:.0f}" text-anchor="end">'
                         f"{lab}{suffix_for(series[1].get('unit', ''))}</text>\n")
        parts.append(f'<g class="axis-label">\n{labels_r}</g>')
    # x labels
    xl = "".join(
        f'<text x="{x_of(i):.0f}" y="1305">{x}</text>\n'
        for i, x in enumerate(xs)
    )
    parts.append(f'<g class="month-label">\n{xl}</g>')
    # series lines, dots, peak labels
    for si, s in enumerate(series):
        pts = " ".join(
            f"{x_of(i):.0f},{y_of(s, p['y']):.0f}"
            for i, p in enumerate(s["points"])
        )
        parts.append(
            f'<polyline id="{beat_id}-line-{si}" class="series-line" '
            f'data-dot="{beat_id}-dot-{si}" points="{pts}" '
            f'fill="none" stroke="{s["color"]}" stroke-width="7" '
            f'stroke-linecap="round" stroke-linejoin="round" />'
        )
        x0, y0 = x_of(0), y_of(s, s["points"][0]["y"])
        parts.append(
            f'<circle id="{beat_id}-dot-{si}" r="13" fill="{s["color"]}" '
            f'stroke="#f6f1e7" stroke-width="4" cx="{x0:.0f}" cy="{y0:.0f}" '
            f'opacity="0" />'
        )
        peak_i = max(range(n), key=lambda i: s["points"][i]["y"])
        px, py = x_of(peak_i), y_of(s, s["points"][peak_i]["y"])
        unit = s.get("unit", "")
        val = s["points"][peak_i]["y"]
        lab = f"{val:g}{suffix_for(unit)}"
        # stagger peak labels vertically per series: when two series peak
        # at the same point (both clamped to y=480, x=860) the labels
        # would otherwise sit exactly on top of each other.
        peak_y = max(py - 18, 480) + si * 60
        parts.append(
            f'<text id="{beat_id}-peak-{si}" class="peak-label" '
            f'x="{min(px + 12, 860):.0f}" y="{peak_y:.0f}" '
            f'fill="{s["color"]}" opacity="0">{lab}</text>'
        )
    return "\n".join(parts)


def build_lines_html(lines, css_class, top_start, top_step):
    """Kinetic text lines -> HTML. lines: [{text, accent: [word idx]}]."""
    out = []
    for li, line in enumerate(lines):
        words = []
        for wi, word in enumerate(line["text"].split()):
            cls = "w red" if wi in line.get("accent", []) else "w"
            words.append(f'<span class="{cls}">{word}</span>')
        top = top_start + li * top_step
        out.append(
            f'<div class="{css_class}" style="top: {top}px;">'
            + " ".join(words) + "</div>"
        )
    return "\n".join(out)


def fill_component(template_path, subs):
    """Load a component fragment, substitute %%KEY%% placeholders, split
    it at the <!--TIMELINE--> marker into (markup, timeline_js)."""
    text = open(template_path).read()
    for key, val in subs.items():
        text = text.replace(f"%%{key}%%", str(val))
    if "<!--TIMELINE-->" not in text:
        raise RuntimeError(f"{template_path} has no <!--TIMELINE--> marker")
    markup, js = text.split("<!--TIMELINE-->", 1)
    return markup.strip(), js.strip()


def build_index(templates_dir, scenes, bounds, total):
    base = open(os.path.join(templates_dir, "base.html")).read()
    beats_html, timeline_js = [], []
    for i, (beat, (start, end)) in enumerate(zip(scenes["beats"], bounds)):
        beat_id = f"beat{i + 1}"
        duration = round(end - start + 0.8, 2)  # 0.4s crossfade each side
        comp = os.path.join(
            templates_dir, "components", f"{beat['type']}.html"
        )
        subs = {
            "ID": beat_id,
            "START": f"{max(0.0, start - 0.4):.2f}",
            "DURATION": f"{duration:.2f}",
            "END": f"{end:.2f}",
        }
        data = beat.get("data", {})
        if beat["type"] == "kinetic":
            subs["EYEBROW"] = data.get("eyebrow", "")
            subs["LINES_HTML"] = build_lines_html(
                data["lines"], "hook-line", 660, 140
            )
            last_top = 660 + (len(data["lines"]) - 1) * 140
            subs["SWOOSH_PATH"] = (
                f"M 330 {last_top + 150} C 480 {last_top + 180}, "
                f"620 {last_top + 180}, 760 {last_top + 145}"
            )
        elif beat["type"] == "chart":
            subs["TITLE"] = data.get("title", "")
            subs["SUB"] = data.get("sub", "")
            subs["CAPTION"] = data.get("caption", "")
            subs["CHART_SVG"] = build_chart_svg(beat_id, data)
        elif beat["type"] == "stickman":
            subs["OBJECT_LABEL"] = data.get("object_label", "")
            subs["PERSON_LABEL"] = f"{data.get('person_height', '')} m"
            subs["STRETCH_LABEL"] = data.get("stretch_label", "")
            subs["NOTE"] = data.get("note", "")
            try:
                stretch = float(
                    "".join(
                        c for c in str(data.get("stretch_label", "0"))
                        if c.isdigit() or c == "."
                    )
                )
                obj_h = float(data.get("object_height", 1) or 1)
                scale = 1 + min(0.12, max(0.03, stretch / obj_h * 20))
            except (TypeError, ValueError):
                scale = 1.07
            subs["STRETCH_SCALE"] = f"{scale:.3f}"
        elif beat["type"] == "diagram":
            subs["TITLE"] = data.get("title", "")
            parts_svg = []
            for pi, part in enumerate(data.get("parts", [])):
                parts_svg.append(
                    f'<path id="{beat_id}-part-{pi}" d="{part["path"]}" '
                    f'fill="none" stroke="#1c1c1c" stroke-width="8" '
                    f'stroke-linecap="round" />'
                )
                parts_svg.append(
                    f'<text id="{beat_id}-label-{pi}" class="part-label" '
                    f'x="{part["x"]}" y="{part["y"]}" opacity="0">'
                    f"{part['label']}</text>"
                )
            subs["PARTS_SVG"] = "\n".join(parts_svg)
            subs["PART_COUNT"] = str(len(data.get("parts", [])))
        elif beat["type"] == "closing":
            subs["LINES_HTML"] = build_lines_html(
                data["lines"], "close-line", 780, 130
            )
            subs["SUB"] = data.get("sub", "")
        markup, js = fill_component(comp, subs)
        if i > 0:
            # every beat after the first starts hidden; the timeline fades it in
            markup = markup.replace('class="beat clip"',
                                    'class="beat clip" style="opacity:0;"', 1)
        beats_html.append(markup)
        timeline_js.append(
            f"// ---- {beat_id} ({beat['type']}) "
            f"{start:.2f}s - {end:.2f}s ----\n"
            f"var S = {start:.2f}, E = {end:.2f};\n{js}"
        )
    html = base.replace("%%BEATS%%", "\n".join(beats_html))
    html = html.replace("%%TIMELINE%%", "\n".join(timeline_js))
    html = html.replace("%%TOTAL%%", f"{total:.2f}")
    return html


def main():
    parser = argparse.ArgumentParser(description="draw the scenes")
    parser.add_argument("--scenes", required=True,
                        help="script.json from draft.py")
    parser.add_argument("--audio", required=True, help="narration wav")
    parser.add_argument("--templates", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--work-dir", required=True,
                        help="HyperFrames project dir to build in")
    parser.add_argument("--words", default=None,
                        help="words.json; runs faster-whisper if omitted")
    parser.add_argument("--model", default="base")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.work_dir, exist_ok=True)
    scenes = json.load(open(args.scenes))

    if args.words:
        words = json.load(open(args.words))
    else:
        from captions import whisper_words  # noqa: PLC0415

        words = whisper_words(args.audio, args.model)
    with open(os.path.join(args.out_dir, "words.json"), "w") as f:
        json.dump(words, f, indent=2)

    bounds = beat_boundaries(scenes["script"], scenes["beats"], words)
    total = round((words[-1]["e"] if words else 0) + 0.7, 2)
    print("beat boundaries:")
    for beat, (s, e) in zip(scenes["beats"], bounds):
        print(f"  {beat['type']:9s} {s:6.2f} - {e:6.2f}")
    print(f"total duration: {total:.2f}s")
    timings = {
        "total": total,
        "beats": [
            {"type": b["type"], "start": round(s, 2), "end": round(e, 2)}
            for b, (s, e) in zip(scenes["beats"], bounds)
        ],
    }
    with open(os.path.join(args.out_dir, "timings.json"), "w") as f:
        json.dump(timings, f, indent=2)

    # copy the project shell (config, package, vendored assets)
    for name in ("hyperframes.json", "package.json", "meta.json"):
        shutil.copy(os.path.join(args.templates, name),
                    os.path.join(args.work_dir, name))
    vendor_src = os.path.join(args.templates, "vendor")
    vendor_dst = os.path.join(args.work_dir, "vendor")
    if os.path.exists(vendor_dst):
        shutil.rmtree(vendor_dst)
    shutil.copytree(vendor_src, vendor_dst)

    html = build_index(args.templates, scenes, bounds, total)
    with open(os.path.join(args.work_dir, "index.html"), "w") as f:
        f.write(html)
    print(f"wrote {os.path.join(args.work_dir, 'index.html')}")

    env = dict(os.environ)
    env["TMPDIR"] = os.path.abspath(os.path.join(args.work_dir, "..", "tmp"))
    os.makedirs(env["TMPDIR"], exist_ok=True)
    for cmd in (
        ["npx", "--yes", "hyperframes@0.8.188", "check"],
        ["npx", "--yes", "hyperframes@0.8.188", "render"],
    ):
        print("+ " + " ".join(cmd), flush=True)
        subprocess.run(cmd, cwd=args.work_dir, env=env, check=True)

    renders = sorted(
        glob.glob(os.path.join(args.work_dir, "renders", "*.mp4")),
        key=os.path.getmtime,
    )
    if not renders:
        raise RuntimeError("hyperframes render produced no mp4")
    silent = os.path.join(args.out_dir, "silent.mp4")
    shutil.copy(renders[-1], silent)
    print(f"wrote {silent} (from {renders[-1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
