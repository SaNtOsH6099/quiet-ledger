#!/usr/bin/env python3
"""The brain: provider rotation for the pipeline's AI calls.

Calls the brain providers in order (Groq -> Gemini -> NVIDIA -> local
small model if one is configured). Each provider takes a comma-separated
list of keys in one secret, and the rotation tries every key of a
provider before moving to the next:
  GROQ_API_KEYS, GEMINI_API_KEYS, NVIDIA_API_KEYS
  LLAMA_MODEL_PATH (optional, local lifeboat leg)
Provider order: Groq, Gemini, NVIDIA NIM, local.
NOTE: NVIDIA NIM free access is prototyping-only per NVIDIA's own FAQ,
so it is a fallback leg here, never the primary brain.

Stdlib only. Keys come from the environment, never from files.
Used by draft.py (script + beats), codegen.py (scene code), and
repair.py (self-heal): they all call generate() here so the rotation
lives in exactly one place.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error


def split_sentences(script):
    """Split narration into sentences on . ! ? followed by a space."""
    parts = re.split(r"(?<=[.!?])\s+", script.strip())
    return [p for p in parts if p]



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
    # Best capable first. Tested 2026-11-06 against the user's keys:
    # the 550B replies, the 30B replies, the 120B returns 404 (not
    # available to this account) so it is not listed here.
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
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

# Codegen (writing scene code) is the most demanding task, so it tries
# the most capable model first: the Nemotron 550B on NVIDIA NIM, which
# replies (tested 2026-11-06). Falls back to Groq, then Gemini, then
# the local lifeboat, same as the default order.
PROVIDERS_CODEGEN = [
    ("nvidia", "NVIDIA_API_KEYS", call_nvidia),
    ("groq", "GROQ_API_KEYS", call_groq),
    ("gemini", "GEMINI_API_KEYS", call_gemini),
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


def generate(system, user, validate, label, order=None):
    """One brain call: try each provider in turn, each key in turn, until
    one returns a reply that passes validate. A key that returns bad
    JSON gets a second chance on a later pass, because the failure is
    the model's output, not the key. A key that fails auth or rate
    limits is not retried. Returns (parsed object, provider name).
    `order` overrides the provider order: codegen passes the NVIDIA
    order (most capable first) because writing scene code is the most
    demanding task; the default order is used for drafting."""
    providers = order if order is not None else PROVIDERS
    last_error = "no providers configured"
    for name, env_name, fn in providers:
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


