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
Calls the brain providers in order (Groq -> Gemini -> NVIDIA -> local
small model if one is configured).

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
import time
import urllib.request
import urllib.error

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


def split_sentences(script):
    """Split narration into sentences on . ! ? followed by a space."""
    parts = re.split(r"(?<=[.!?])\s+", script.strip())
    return [p for p in parts if p]


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


class KeyFailure(Exception):
    """One key failed with a 429 or an auth error: try the next key."""


class ProviderFailure(Exception):
    """The provider failed for a reason another key will not fix."""


class RetryableFailure(Exception):
    """The attempt failed but the provider and key are fine; try the
    next key (or the same key again on a later pass)."""


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
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=data,
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
            if e.code == 400 and "json_validate_failed" in body:
                raise RetryableFailure(
                    "HTTP 400: model output failed JSON validation"
                )
            if e.code in (500, 502, 503, 504) and attempt < 2:
                wait = 5 if attempt == 0 else 15
                print(f"  transient HTTP {e.code}, retrying in {wait}s",
                      flush=True)
                time.sleep(wait)
                continue
            raise ProviderFailure(f"HTTP {e.code}: {body}")
        except OSError as e:
            if attempt < 2:
                wait = 5 if attempt == 0 else 15
                print(f"  request failed ({e}), retrying in {wait}s",
                      flush=True)
                time.sleep(wait)
                continue
            raise ProviderFailure(f"request failed: {e}")
    raise ProviderFailure("request failed after retries")


def call_groq(key, system, user):
    return _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "reasoning_effort": "low",
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
            "max_completion_tokens": 8192,
        },
    )["choices"][0]["message"]["content"]


def call_gemini(key, system, user):
    # gemini-2.5-flash was retired for new users; Google's own error
    # message points at gemini-3.8-flash. Override with GEMINI_MODEL.
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    resp = _post_json(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key=" + key,
        {"Content-Type": "application/json"},
        {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.7,
                "maxOutputTokens": 8192,
            },
        },
    )
    return resp["candidates"][0]["content"]["parts"][0]["text"]


NVIDIA_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "deepseek-ai/deepseek-v4.1-flash",
]


def call_nvidia(key, system, user):
    # NVIDIA NIM hosted endpoint (OpenAI-compatible). Free access is
    # prototyping-only per NVIDIA's own FAQ, so this is a fallback leg,
    # never the primary brain. Which models a key can use varies by
    # account, so try several in order; a 404 means that model is not
    # available to this account, and a timeout means it hung, so move
    # to the next model instead of abandoning the leg. Override the
    # list with NVIDIA_MODELS (comma-separated) or a single model with
    # NVIDIA_MODEL.
    models = os.environ.get("NVIDIA_MODELS")
    if models:
        candidates = [m.strip() for m in models.split(",") if m.strip()]
    elif os.environ.get("NVIDIA_MODEL"):
        candidates = [os.environ["NVIDIA_MODEL"]]
    else:
        candidates = NVIDIA_MODELS
    last_error = None
    for model in candidates:
        try:
            return _post_json(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                {"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7,
                    "max_tokens": 8192,
                },
                timeout=45,
            )["choices"][0]["message"]["content"]
        except ProviderFailure as e:
            if "HTTP 404" in str(e):
                print(f"  nvidia model {model} not available to this "
                      "account", flush=True)
                last_error = e
                continue
            raise
        except (TimeoutError, OSError) as e:
            print(f"  nvidia model {model} timed out, trying next",
                  flush=True)
            last_error = ProviderFailure(f"timeout on {model}: {e}")
            continue
    raise last_error if last_error else ProviderFailure("no NVIDIA model answered")


def call_local(_key, system, user):
    """Lifeboat leg: a small local model, only if one is configured."""
    path = os.environ.get("LLAMA_MODEL_PATH")
    if not path:
        raise ProviderFailure("no LLAMA_MODEL_PATH set, local leg skipped")
    from llama_cpp import Llama  # noqa: PLC0415 - optional dependency

    llm = Llama(model_path=path, n_ctx=4096, verbose=False)
    out = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
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


def _parse_json(text):
    """Parse a brain reply leniently: strip markdown fences, extract the
    first JSON object if there is surrounding text, and unwrap a
    double-encoded JSON string."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        t = t.strip()
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if not m:
            raise
        obj = json.loads(m.group(0))
    if isinstance(obj, str):
        obj = json.loads(obj)
    if isinstance(obj, list):
        # The model sometimes wraps the draft in an array; take the
        # first object in it.
        for item in obj:
            if isinstance(item, dict):
                return item
    return obj


def generate(system, user, validate, label):
    """One brain call: try each provider in turn, each key in turn, until
    one returns a reply that passes validate. A key that returns bad
    JSON gets a second chance on a later pass, because the failure is
    the model's output, not the key. A key that fails auth or rate
    limits is not retried. Returns (parsed object, provider name)."""
    last_error = "no providers configured"
    for name, env_name, fn in PROVIDERS:
        keys = _keys_for(env_name)
        if env_name and not keys:
            print(f"  {name}: no keys in {env_name}, skipped", flush=True)
            continue
        dead_keys = set()
        for pass_no in range(2):
            provider_down = False
            for ki, key in enumerate(keys):
                if ki in dead_keys:
                    continue
                attempt = (
                    f"{name} key {ki + 1}/{len(keys)}"
                    if len(keys) > 1
                    else name
                )
                if pass_no:
                    attempt += f" (retry {pass_no + 1})"
                print(f"trying brain for {label}: {attempt}", flush=True)
                try:
                    text = fn(key, system, user)
                except RetryableFailure as e:
                    print(f"  {attempt} failed ({e}), trying next key",
                          flush=True)
                    last_error = f"{attempt}: {e}"
                    continue
                except KeyFailure as e:
                    print(f"  {attempt} failed ({e}), trying next key",
                          flush=True)
                    last_error = f"{attempt}: {e}"
                    dead_keys.add(ki)
                    continue
                except ProviderFailure as e:
                    print(f"  {name} failed: {e}", flush=True)
                    last_error = f"{name}: {e}"
                    provider_down = True
                    break
                except Exception as e:  # noqa: BLE001 - rotation survives anything
                    print(f"  {name} failed unexpectedly: {e}", flush=True)
                    last_error = f"{name}: {e}"
                    provider_down = True
                    break
                try:
                    obj = _parse_json(text)
                except json.JSONDecodeError as e:
                    print(f"  {attempt} returned invalid JSON: {e}", flush=True)
                    print(f"  raw reply (first 400 chars): {text[:400]!r}",
                          flush=True)
                    last_error = f"{attempt} returned invalid JSON"
                    continue
                problems = validate(obj)
                if problems:
                    print(f"  {attempt} {label} failed validation:", flush=True)
                    for p in problems:
                        print(f"    - {p}", flush=True)
                    print(f"  raw reply (first 400 chars): {text[:400]!r}",
                          flush=True)
                    last_error = (
                        f"{attempt} {label} failed validation: {problems[0]}"
                    )
                    continue
                print(f"  {attempt} produced a valid {label}", flush=True)
                return obj, name
            if provider_down:
                break
    raise RuntimeError(
        f"all brain providers failed on {label}, last error: {last_error}"
    )


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
