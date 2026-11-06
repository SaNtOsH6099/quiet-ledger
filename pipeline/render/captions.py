#!/usr/bin/env python3
"""Word-timed captions, burned in later at assembly.

Two modes:
  1. captions.py --words words.json --script script.json --out captions.ass
     Build the .ass from existing whisper word timings.
  2. captions.py --audio narration.wav --script script.json --out captions.ass
     --words-out words.json
     Run faster-whisper first (base model, word timestamps), then build.

Caption style, from the approved demo: 3-4 word chunks, big bold white
with a black outline, lower third (about 70% down a 1080x1920 frame).
If whisper's word count differs from the script's, the captions use
whisper's own words (what was actually spoken) and warn, instead of
failing the run.
"""
import argparse
import json
import sys


def whisper_words(audio_path, model="base"):
    from faster_whisper import WhisperModel  # noqa: PLC0415

    print(f"transcribing {audio_path} with faster-whisper ({model})...",
          flush=True)
    model_obj = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _info = model_obj.transcribe(audio_path, word_timestamps=True)
    words = []
    for seg in segments:
        for w in seg.words:
            words.append({"w": w.word, "s": round(w.start, 3),
                          "e": round(w.end, 3)})
    print(f"  {len(words)} words timed", flush=True)
    return words


def chunk_words(timed):
    """Split timed words into 3-4 word caption chunks, preferring breaks
    at sentence ends. Merge a tiny trailing chunk into the previous one."""
    chunks, cur = [], []
    for item in timed:
        cur.append(item)
        if len(cur) >= 4 or (item["w"].endswith(".") and len(cur) >= 2):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    if len(chunks) > 1 and len(chunks[-1]) < 2:
        chunks[-2].extend(chunks[-1])
        chunks.pop()
    events = []
    for ch in chunks:
        start = max(0.0, ch[0]["s"] - 0.05)
        end = ch[-1]["e"] + 0.12
        text = " ".join(w["w"].strip() for w in ch)
        events.append([start, end, text])
    # clamp: no two captions may overlap on screen
    for i in range(len(events) - 1):
        events[i][1] = min(events[i][1], events[i + 1][0] - 0.02)
        if events[i][1] <= events[i][0]:
            events[i][1] = events[i][0] + 0.20
    return events


def fmt(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans,76,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,0,2,60,60,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(script_text, words, out_path):
    script_words = script_text.split()
    if len(words) == len(script_words):
        timed = [
            {"w": script_words[i], "s": words[i]["s"], "e": words[i]["e"]}
            for i in range(len(words))
        ]
    else:
        print(f"warning: whisper timed {len(words)} words, script has "
              f"{len(script_words)}; captioning what was spoken",
              file=sys.stderr)
        timed = [{"w": w["w"], "s": w["s"], "e": w["e"]} for w in words]
    events = chunk_words(timed)
    body = "\n".join(
        f"Dialogue: 0,{fmt(s)},{fmt(e)},Default,,0,0,0,,{t}"
        for s, e, t in events
    )
    with open(out_path, "w") as f:
        f.write(ASS_HEADER + body + "\n")
    print(f"wrote {out_path}: {len(events)} caption events")
    for s, e, t in events:
        print(f"  {s:5.2f}-{e:5.2f}  {t}")
    return events


def main():
    parser = argparse.ArgumentParser(description="word-timed captions")
    parser.add_argument("--script", required=True,
                        help="script.json from draft.py")
    parser.add_argument("--out", required=True, help="captions.ass to write")
    parser.add_argument("--words", default=None,
                        help="words.json from faster-whisper")
    parser.add_argument("--audio", default=None,
                        help="narration wav; runs faster-whisper if given")
    parser.add_argument("--words-out", default=None,
                        help="where to save whisper timings")
    parser.add_argument("--model", default="base")
    args = parser.parse_args()
    if not args.words and not args.audio:
        print("need --words or --audio", file=sys.stderr)
        return 2
    if args.words:
        words = json.load(open(args.words))
    else:
        words = whisper_words(args.audio, args.model)
    if args.words_out:
        with open(args.words_out, "w") as f:
            json.dump(words, f, indent=2)
    script_text = json.load(open(args.script))["script"]
    build_ass(script_text, words, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
