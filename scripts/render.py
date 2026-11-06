#!/usr/bin/env python3
"""Draw the scenes: brain-written scene code -> HyperFrames composition
-> silent frames.

The scene code comes from codegen.py (one markup + timeline per beat,
written by the brain for that specific scene; no fixed templates).
This script only assembles it: beat boundaries come from the whisper
word timings, the code is slotted into templates/base.html, and
HyperFrames checks and renders the result.

Steps:
  1. Get whisper word timings for the narration (from --words, or by
     running faster-whisper here). Beat boundaries come from the words:
     a beat starts at the first word of its first sentence and ends at
     the last word of its last sentence.
  2. Build a HyperFrames index.html from templates/base.html and the
     brain-written markup + timeline for each beat.
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

import guardrails  # noqa: E402 - format canvas + base template

W, H = 1080, 1920


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


def build_index(templates_dir, scenes, bounds, total):
    """Assemble the HyperFrames page from the brain-written beat code.
    No fixed templates: each beat's markup + timeline comes from
    scenes["code"], written by codegen.py for that specific scene.
    This only fills in the beat id, start, and duration, and slots the
    beats into base.html."""
    if "code" not in scenes:
        raise RuntimeError(
            "script.json has no 'code'; run codegen.py after draft.py")
    if len(scenes["code"]) != len(scenes["beats"]):
        raise RuntimeError(
            f"code has {len(scenes['code'])} beats but the plan has "
            f"{len(scenes['beats'])}; re-run codegen.py")
    fmt = scenes.get("format", "shorts")
    base_name = guardrails.get(fmt)["base_template"]
    base = open(os.path.join(templates_dir, base_name)).read()
    beats_html, timeline_js = [], []
    for i, (beat, code, (start, end)) in enumerate(
            zip(scenes["beats"], scenes["code"], bounds)):
        beat_id = f"beat{i + 1}"
        duration = round(end - start + 0.8, 2)  # 0.4s crossfade each side
        markup = code["markup"].replace("%%ID%%", beat_id)
        markup = markup.replace("%%START%%", f"{max(0.0, start - 0.4):.2f}")
        markup = markup.replace("%%DURATION%%", f"{duration:.2f}")
        if "%%" in markup:
            raise RuntimeError(
                f"{beat_id} markup still has an unfilled placeholder")
        js = code["timeline"].replace("%%ID%%", beat_id)
        if "%%" in js:
            raise RuntimeError(
                f"{beat_id} timeline still has an unfilled placeholder")
        if i > 0:
            # every beat after the first starts hidden; the timeline fades it in
            markup = markup.replace('class="beat clip"',
                                    'class="beat clip" style="opacity:0;"', 1)
        beats_html.append(markup)
        idea = beat.get("idea", "")[:60]
        timeline_js.append(
            f"// ---- {beat_id} {start:.2f}s - {end:.2f}s "
            f"({idea}) ----\n"
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
    for i, (beat, (s, e)) in enumerate(zip(scenes["beats"], bounds)):
        idea = beat.get("idea", "")[:50]
        print(f"  beat{i + 1} {s:6.2f} - {e:6.2f}  {idea}")
    print(f"total duration: {total:.2f}s")
    timings = {
        "total": total,
        "beats": [
            {"idea": b.get("idea", "")[:80], "start": round(s, 2),
             "end": round(e, 2)}
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
