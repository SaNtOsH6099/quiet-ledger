#!/usr/bin/env python3
"""Draft the words and the scene plan for one topic.

Calls the brain providers in order (Groq -> Gemini -> NVIDIA -> local
small model if one is configured) and asks for strict JSON:
  {"script": "...", "beats": [...]}
The script is one continuous narration, about 70-90 words. Each beat covers
one or more sentences of the script and carries the data one drawn scene
needs. Output is validated hard: a bad draft fails the run instead of
producing a broken file downstream.

Stdlib only. Keys come from the environment, never from files. Each
provider takes a comma-separated list of keys in one secret, and the
rotation tries every key of a provider before moving to the next:
  GROQ_API_KEYS, GEMINI_API_KEYS, NVIDIA_API_KEYS
  LLAMA_MODEL_PATH (optional, local lifeboat leg)
Provider order: Groq, Gemini, NVIDIA NIM, local.
NOTE: NVIDIA NIM free access is prototyping-only per NVIDIA's own FAQ,
so it is a fallback leg here, never the primary brain.
"""
import json
import os
import re
import sys
import urllib.request
import urllib.error

BEAT_TYPES = ("kinetic", "chart", "stickman", "diagram", "closing")

# Fields each beat type must carry in its "data" object.
REQUIRED_DATA = {
    "kinetic": ("eyebrow", "lines"),
    "chart": ("title", "sub", "series"),
    "stickman": ("object_label", "object_height", "person_height", "stretch_label"),
    "diagram": ("title", "parts"),
    "closing": ("lines", "sub"),
}

SYSTEM_PROMPT = """You write short narrated explainers. Each one is a single
continuous narration of 70 to 90 words about one surprising fact, written
in plain spoken language, one idea per sentence, no em dashes anywhere.
You also plan the drawn scenes that go with it. Every scene is drawn in
code (line drawings, charts, stick figures, kinetic text). No photos, no
generated imagery, nothing that is not drawn.

Return ONLY a JSON object with this exact shape:
{
  "script": "Full narration text. Sentences separated by single spaces.",
  "beats": [
    {
      "type": "kinetic",
      "sentences": [0],
      "data": {
        "eyebrow": "SHORT KICKER IN CAPS",
        "lines": [{"text": "LINE ONE", "accent": [1]}, {"text": "LINE TWO", "accent": []}]
      }
    },
    {
      "type": "chart",
      "sentences": [1, 2],
      "data": {
        "title": "CHART TITLE",
        "sub": "what the two lines mean",
        "caption": "one short line under the chart",
        "series": [
          {"label": "first", "color": "#d9481f", "unit": "deg C",
           "points": [{"x": "Jan", "y": 5}, {"x": "Feb", "y": 6}]},
          {"label": "second", "color": "#2b5ea7", "unit": "cm",
           "points": [{"x": "Jan", "y": 0}, {"x": "Feb", "y": 1}]}
        ]
      }
    },
    {
      "type": "stickman",
      "sentences": [3],
      "data": {
        "object_label": "330 m",
        "object_height": 330,
        "person_height": 1.8,
        "stretch_label": "+15 cm",
        "note": "(stretch exaggerated)"
      }
    },
    {
      "type": "diagram",
      "sentences": [4],
      "data": {
        "title": "HOW IT WORKS",
        "parts": [
          {"path": "M100,900 L500,900", "label": "heat in", "x": 300, "y": 860},
          {"path": "M500,900 L900,600", "label": "metal grows", "x": 700, "y": 700}
        ]
      }
    },
    {
      "type": "closing",
      "sentences": [5],
      "data": {
        "lines": [{"text": "NEVER THE SAME", "accent": []}, {"text": "HEIGHT TWICE", "accent": [1]}],
        "sub": "one quiet closing line"
      }
    }
  ]
}

Rules:
- "sentences" are 0-based indices into the script's sentences. Every
  sentence must appear in exactly one beat, in order, with no gaps.
- Use 4 to 6 beats. The first beat is always type "kinetic", the last
  always type "closing". Use "chart" only when the fact has real numbers
  that rise or fall over time. Use "stickman" when a size comparison
  makes the fact land. Use "diagram" when a process needs showing.
- Chart points: 6 to 12 points per series, x labels short (months or
  plain words), y plain numbers. Both series share the same x labels.
- Kinetic and closing lines: 2 to 3 lines, 1 to 3 words each, ALL CAPS.
  "accent" lists the 0-based word positions to colour in red.
- Diagram paths are SVG path strings inside a 1080x1920 frame, drawn
  left to right, top to bottom. Keep them simple: straight lines and
  gentle curves only.
- Numbers in the script must be true. If you are not sure of a number,
  leave the number out and say the idea in words instead.
- No em dashes. No markdown. No text outside the JSON object.
"""


def split_sentences(script):
    """Split narration into sentences on . ! ? followed by a space."""
    parts = re.split(r"(?<=[.!?])\s+", script.strip())
    return [p for p in parts if p]


def validate_output(obj):
    """Check a brain reply against the schema. Returns a list of problems."""
    problems = []
    if not isinstance(obj, dict):
        return ["top level is not a JSON object"]
    script = obj.get("script")
    beats = obj.get("beats")
    if not isinstance(script, str) or not script.strip():
        problems.append("missing or empty 'script'")
        return problems
    if "\u2014" in script or "\u2013" in script:
        problems.append("script contains a dash character (use plain words)")
    words = script.split()
    if not 55 <= len(words) <= 110:
        problems.append(f"script is {len(words)} words, want 55 to 110")
    if not isinstance(beats, list) or not 3 <= len(beats) <= 7:
        problems.append("beats must be a list of 3 to 7 items")
        return problems
    sentences = split_sentences(script)
    seen = []
    for i, beat in enumerate(beats):
        if not isinstance(beat, dict):
            problems.append(f"beat {i} is not an object")
            continue
        btype = beat.get("type")
        if btype not in BEAT_TYPES:
            problems.append(f"beat {i} has unknown type {btype!r}")
            continue
        if i == 0 and btype != "kinetic":
            problems.append("first beat must be type 'kinetic'")
        if i == len(beats) - 1 and btype != "closing":
            problems.append("last beat must be type 'closing'")
        idx = beat.get("sentences")
        if not isinstance(idx, list) or not idx or not all(
            isinstance(n, int) and 0 <= n < len(sentences) for n in idx
        ):
            problems.append(f"beat {i} has bad sentence indices {idx!r}")
            continue
        seen.extend(idx)
        data = beat.get("data")
        if not isinstance(data, dict):
            problems.append(f"beat {i} is missing its data object")
            continue
        for field in REQUIRED_DATA[btype]:
            if field not in data:
                problems.append(f"beat {i} ({btype}) is missing data.{field}")
        if btype == "chart":
            series = data.get("series")
            if not isinstance(series, list) or len(series) < 1:
                problems.append(f"beat {i} chart needs at least one series")
            else:
                xs = None
                for s in series:
                    pts = s.get("points") if isinstance(s, dict) else None
                    if not isinstance(pts, list) or not 4 <= len(pts) <= 12:
                        problems.append(f"beat {i} chart series needs 4 to 12 points")
                        break
                    labels = [p.get("x") for p in pts]
                    if xs is None:
                        xs = labels
                    elif labels != xs:
                        problems.append(f"beat {i} chart series do not share x labels")
    if seen != sorted(seen) or sorted(seen) != list(range(len(sentences))):
        problems.append(
            f"beats must cover sentences 0..{len(sentences) - 1} exactly once, got {seen}"
        )
    return problems


class KeyFailure(Exception):
    """One key failed with a 429 or an auth error: try the next key."""


class ProviderFailure(Exception):
    """The provider failed for a reason another key will not fix."""


def _post_json(url, headers, payload, timeout=120):
    # Groq's API sits behind Cloudflare, whose edge blocks the default
    # Python user agent (HTTP 403, error code 1010). A browser user
    # agent passes the check; the call itself is a normal authenticated
    # API request with a valid key.
    merged = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        **headers,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=merged,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        if e.code in (401, 403, 429):
            raise KeyFailure(f"HTTP {e.code}: {body}")
        raise ProviderFailure(f"HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise ProviderFailure(f"network error: {e}")


def call_groq(key, topic):
    return _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Topic: {topic}"},
            ],
            "reasoning_effort": "low",
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        },
    )["choices"][0]["message"]["content"]


def call_gemini(key, topic):
    # gemini-2.5-flash was retired for new users; Google's own error
    # message points at gemini-3.8-flash. Override with GEMINI_MODEL.
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    resp = _post_json(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key=" + key,
        {"Content-Type": "application/json"},
        {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": f"Topic: {topic}"}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.7,
            },
        },
    )
    return resp["candidates"][0]["content"]["parts"][0]["text"]


def call_nvidia(key, topic):
    # NVIDIA NIM hosted endpoint (OpenAI-compatible). Free access is
    # prototyping-only per NVIDIA's own FAQ, so this is a fallback leg,
    # never the primary brain. Model names are listed on build.nvidia.com;
    # override with NVIDIA_MODEL if the default is retired.
    # nemotron-3-super-120b-a12b verified answering on the free key
    # (Oct 2026 tests); the old llama-3.1-nemotron-70b default returns
    # 404. Override with NVIDIA_MODEL if it is retired.
    model = os.environ.get(
        "NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b"
    )
    return _post_json(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Topic: {topic}"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        },
    )["choices"][0]["message"]["content"]


def call_local(_key, topic):
    """Lifeboat leg: a small local model, only if one is configured."""
    path = os.environ.get("LLAMA_MODEL_PATH")
    if not path:
        raise ProviderFailure("no LLAMA_MODEL_PATH set, local leg skipped")
    from llama_cpp import Llama  # noqa: PLC0415 - optional dependency

    llm = Llama(model_path=path, n_ctx=4096, verbose=False)
    out = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Topic: {topic}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    return out["choices"][0]["message"]["content"]


# (provider name, secret holding its comma-separated keys, call function)
# Keys are tried in order within a provider; a 429 or auth error moves to
# the next key, any other failure moves to the next provider.
PROVIDERS = [
    ("groq", "GROQ_API_KEYS", call_groq),
    ("gemini", "GEMINI_API_KEYS", call_gemini),
    ("nvidia", "NVIDIA_API_KEYS", call_nvidia),
    ("local", None, call_local),
]


def _keys_for(env_name):
    if not env_name:
        return [None]
    return [
        k.strip()
        for k in os.environ.get(env_name, "").split(",")
        if k.strip()
    ]


def draft(topic):
    """Try each provider in turn, each key in turn, until one returns a
    valid draft."""
    last_error = "no providers configured"
    for name, env_name, fn in PROVIDERS:
        keys = _keys_for(env_name)
        if env_name and not keys:
            print(f"  {name}: no keys in {env_name}, skipped", flush=True)
            continue
        for ki, key in enumerate(keys):
            label = (
                f"{name} key {ki + 1}/{len(keys)}"
                if len(keys) > 1
                else name
            )
            print(f"trying brain: {label}", flush=True)
            try:
                text = fn(key, topic)
            except KeyFailure as e:
                print(f"  {label} failed ({e}), trying next key", flush=True)
                last_error = f"{label}: {e}"
                continue
            except ProviderFailure as e:
                print(f"  {name} failed: {e}", flush=True)
                last_error = f"{name}: {e}"
                break
            except Exception as e:  # noqa: BLE001 - rotation survives anything
                print(f"  {name} failed unexpectedly: {e}", flush=True)
                last_error = f"{name}: {e}"
                break
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as e:
                print(f"  {label} returned invalid JSON: {e}", flush=True)
                last_error = f"{label} returned invalid JSON"
                break
            problems = validate_output(obj)
            if problems:
                print(f"  {label} draft failed validation:", flush=True)
                for p in problems:
                    print(f"    - {p}", flush=True)
                last_error = (
                    f"{label} draft failed validation: {problems[0]}"
                )
                break
            print(f"  {label} produced a valid draft", flush=True)
            return obj, name
    raise RuntimeError(f"all brain providers failed, last error: {last_error}")


def main():
    if len(sys.argv) < 3:
        print("usage: draft.py TOPIC OUT_DIR", file=sys.stderr)
        return 2
    topic, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    obj, provider = draft(topic)
    obj["topic"] = topic
    obj["provider"] = provider
    obj["words"] = len(obj["script"].split())
    with open(os.path.join(out_dir, "script.json"), "w") as f:
        json.dump(obj, f, indent=2)
    # human-readable copy, for review and approval
    lines = [f"# {topic}", "", obj["script"], "", "## Beats"]
    for i, beat in enumerate(obj["beats"]):
        sents = " ".join(
            split_sentences(obj["script"])[n] for n in beat["sentences"]
        )
        lines.append(f"{i + 1}. [{beat['type']}] {sents}")
    with open(os.path.join(out_dir, "script.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"drafted with {provider}: {obj['words']} words, "
          f"{len(obj['beats'])} beats")
    return 0


if __name__ == "__main__":
    sys.exit(main())
