#!/usr/bin/env python3
"""Draft the words and the scene plan for one topic.

Two brain calls, each one simple: first the script alone (strict JSON
{"script": "..."}), then the beats for that script (strict JSON
{"beats": [...]}). The script is one continuous narration, about 70-90
words. Each beat covers one or more sentences of the script and carries
a short visual idea for what the scene should show. There are no fixed
beat types; the idea is the brain's creative direction, and codegen.py
turns it into the actual scene code. Output is validated hard: a bad
draft fails the run instead of producing a broken file downstream.
A single call asking for script and beats together failed six test runs
in a row (short scripts, malformed beats), so the job is split in two.
The brain (provider rotation) lives in providers.py; this module
calls generate() there. Stdlib only.
"""
import json
import os
import re
import sys
import time
from pipeline.brain.providers import generate, split_sentences

SCRIPT_PROMPT = '''You write short narrated explainers. Each one is a single
continuous narration of 70 to 90 words about one surprising fact, written
in plain spoken language, one idea per sentence, no em dashes anywhere.
Numbers in the script must be true. If you are not sure of a number,
leave the number out and say the idea in words instead.

Return ONLY a JSON object with this exact shape:
{"script": "Full narration text. Sentences separated by single spaces."}

Rules:
- The script must be 70 to 90 words. Count the words before you answer.
  If it is under 70 words, add another sentence.
- No em dashes. No markdown. No text outside the JSON object.
'''


def beats_prompt(script):
    """Beat-planning prompt for one finished script. A beat is a story
    unit: which sentences it covers and a short visual idea for what
    the scene should show. There are no fixed beat types; the idea is
    the brain's creative direction, and codegen.py turns it into the
    actual scene code. The first beat is the hook, the last is the
    closing."""
    n = len(split_sentences(script))
    return f'''You plan the drawn scenes for a narrated explainer. Every scene
is drawn in code (line drawings, charts, stick figures, kinetic text). No
photos, no generated imagery, nothing that is not drawn.

Here is the narration script. It has {n} sentences, numbered 0 to {n - 1}:
{script}

Return ONLY a JSON object with this exact shape:
{{
  "beats": [
    {{
      "sentences": [0],
      "idea": "Hook: giant kinetic words build one by one, a red swoosh underlines the last word."
    }},
    {{
      "sentences": [1, 2],
      "idea": "A line chart of temperature rising month by month, a dot rides the line, the peak value pops in red."
    }},
    {{
      "sentences": [3],
      "idea": "A tall shape drawn next to a small red person for scale, then it stretches a little taller."
    }},
    {{
      "sentences": [4],
      "idea": "A simple diagram: heat flows in along a path, the metal grows, each part labelled as it draws."
    }},
    {{
      "sentences": [5],
      "idea": "Closing: one quiet line builds word by word, a small red sun draws itself in the corner."
    }}
  ]
}}

Rules:
- "sentences" are 0-based indices into the script's sentences. Every
  sentence must appear in exactly one beat, in order, with no gaps.
- Use 4 to 6 beats. The first beat is the hook: it must stop a
  scroller, big and immediate. The last beat is the closing: quiet,
  one clear line, the thought that lingers.
- "idea" is one or two sentences describing what the scene shows and
  how it moves. Be specific: name the shapes, the numbers, the
  comparison, the motion. A different scene needs a different idea;
  do not repeat the same visual twice in one video.
- The idea must be drawable in code on a 1080x1920 page: lines,
  shapes, charts, text, stick figures. No photos, no video, no
  generated imagery.
- No em dashes. No markdown. No text outside the JSON object.
'''


def validate_script(obj):
    """Check a script-only reply. Returns a list of problems."""
    problems = []
    if not isinstance(obj, dict):
        return ["top level is not a JSON object"]
    script = obj.get("script")
    if not isinstance(script, str) or not script.strip():
        problems.append("missing or empty 'script'")
        return problems
    if "\u2014" in script or "\u2013" in script:
        problems.append("script contains a dash character (use plain words)")
    words = script.split()
    if not 55 <= len(words) <= 110:
        problems.append(f"script is {len(words)} words, want 55 to 110")
    return problems


def validate_beats(obj, script):
    """Check a beats-only reply against one finished script. A beat is
    sentences + a visual idea; there are no fixed types."""
    problems = []
    if not isinstance(obj, dict):
        return ["top level is not a JSON object"]
    beats = obj.get("beats")
    if not isinstance(beats, list) or not 3 <= len(beats) <= 7:
        problems.append("beats must be a list of 3 to 7 items")
        return problems
    sentences = split_sentences(script)
    seen = []
    for i, beat in enumerate(beats):
        if not isinstance(beat, dict):
            problems.append(f"beat {i} is not an object")
            continue
        idx = beat.get("sentences")
        if not isinstance(idx, list) or not idx or not all(
            isinstance(n, int) and 0 <= n < len(sentences) for n in idx
        ):
            problems.append(f"beat {i} has bad sentence indices {idx!r}")
            continue
        seen.extend(idx)
        idea = beat.get("idea")
        if not isinstance(idea, str) or len(idea.strip()) < 10:
            problems.append(f"beat {i} is missing a visual idea")
            continue
        if "\u2014" in idea or "\u2013" in idea:
            problems.append(f"beat {i} idea contains a dash character")
    if seen != sorted(seen) or sorted(seen) != list(range(len(sentences))):
        problems.append(
            f"beats must cover sentences 0..{len(sentences) - 1} exactly once, got {seen}"
        )
    return problems


def validate_output(obj):
    """Check a combined draft against the schema. Returns a list of problems."""
    problems = validate_script(obj)
    if problems:
        return problems
    return validate_beats(obj, obj["script"])


def draft(topic):
    """Two calls, each one simple enough for the model to get right.
    First the script alone (70 to 90 words of narration), then the
    beats for that script. A single call asking for both at once failed
    six test runs in a row: the model wrote short scripts and malformed
    beats. Splitting the job fixes both."""
    script_obj, script_provider = generate(
        SCRIPT_PROMPT,
        f"Topic: {topic}",
        validate_script,
        "script",
    )
    script = script_obj["script"]
    beats_obj, beats_provider = generate(
        beats_prompt(script),
        "Plan the beats for the script above.",
        lambda obj: validate_beats(obj, script),
        "beats",
    )
    obj = {"script": script, "beats": beats_obj["beats"]}
    problems = validate_output(obj)
    if problems:
        raise RuntimeError(f"combined draft failed validation: {problems}")
    print(f"draft ready (script via {script_provider}, "
          f"beats via {beats_provider})", flush=True)
    return obj, f"{script_provider}+{beats_provider}"



def main():
    if len(sys.argv) < 3:
        print("usage: draft.py TOPIC OUT_DIR [--format shorts|longform]",
              file=sys.stderr)
        return 2
    topic, out_dir = sys.argv[1], sys.argv[2]
    fmt = "shorts"
    for a in sys.argv[3:]:
        if a.startswith("--format="):
            fmt = a.split("=", 1)[1]
    os.makedirs(out_dir, exist_ok=True)
    obj, provider = draft(topic)
    obj["topic"] = topic
    obj["provider"] = provider
    obj["words"] = len(obj["script"].split())
    obj["format"] = fmt
    with open(os.path.join(out_dir, "script.json"), "w") as f:
        json.dump(obj, f, indent=2)
    # human-readable copy, for review and approval
    lines = [f"# {topic}", "", obj["script"], "", "## Beats"]
    for i, beat in enumerate(obj["beats"]):
        sents = " ".join(
            split_sentences(obj["script"])[n] for n in beat["sentences"]
        )
        lines.append(f"{i + 1}. {sents}")
        lines.append(f"   Idea: {beat['idea']}")
    with open(os.path.join(out_dir, "script.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"drafted with {provider}: {obj['words']} words, "
          f"{len(obj['beats'])} beats")
    return 0


if __name__ == "__main__":
    sys.exit(main())
