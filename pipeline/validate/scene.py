#!/usr/bin/env python3
"""Validate scene code before it renders.

Muse writes the scene code (one markup + timeline per beat) and this
module checks it against the guardrails, so bad code is caught before
it reaches the render instead of shipping a broken video. It runs in
two places:

  - locally, when Muse writes the code (before the script is pushed);
  - in GitHub Actions, in the ingest job (before the script reaches
    Drive) and in the scenes job (a last check before rendering).

The checks:
  - markup is one beat div with the %%ID%% / %%START%% / %%DURATION%%
    placeholders and no other placeholders left over;
  - big-text lines fit the format's limits (they do not wrap, so a
    long line is cut off at the frame edge);
  - the CSS check measures the actual rendered width of every text
    line from the stylesheet and flags any that would run off the
    frame;
  - timeline is GSAP JS that parses under `node --check` (real JS
    syntax, not a guess) and ends with the hard kill.

The exit fade and hard kill are appended mechanically by append_exit:
a beat can never ship without them, because asking a writer to
remember them failed in testing (the code was written without an
exit on every attempt). The hard kill is the guarantee the beat is
hidden at E; without it the video is broken.

Stdlib only, except node for the JS syntax check and Pillow (via
css_check) for the text-width measurement.
"""
import os
import re
import subprocess
import tempfile

from pipeline.guardrails import rules as guardrails
from pipeline.guardrails import css_check

# The scene-code version. Bump this whenever the validation rules or
# the design system change in a way that makes older scene code
# unreliable. The version is stamped into script.json when the code
# is written; the render job refuses to render code whose stored
# version is older than this one, so an improved validator
# automatically stops old videos from replaying their broken code
# instead of trusting the stored code blindly (the failure that
# shipped entry 3's clipped hook and missing closing text twice).
CODEGEN_VERSION = 1


# The exit every beat gets, appended mechanically (see module docstring).
EXIT_FADE = 'tl.to("#%%ID%%", { opacity: 0, duration: 0.4 }, E - 0.4);'
HARD_KILL = 'tl.set("#%%ID%%", { opacity: 0 }, E);'


def _js_syntax_ok(js):
    """Real JS syntax check via node --check. Returns an error string
    or None. node --check only checks syntax, so undefined names (tl,
    S, E, document) are fine."""
    with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False) as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run(["node", "--check", path],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"node --check could not run: {e}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if r.returncode != 0:
        return (r.stderr.strip() or r.stdout.strip()
                or "node --check failed")[:400]
    return None


def append_exit(timeline):
    """Append the exit fade + hard kill if the writer omitted them.
    The hard kill is the guarantee the beat is hidden at E; without it
    the video is broken. Appending mechanically is reliable where
    asking the writer was not (it omitted them on every attempt)."""
    tl = timeline.rstrip()
    if HARD_KILL in tl:
        return tl
    # If the writer wrote its own exit fade but no hard kill, keep the
    # fade and just add the kill after it.
    if 'tl.to("#%%ID%%", { opacity: 0' in tl:
        return tl + "\n" + HARD_KILL
    return tl + "\n" + EXIT_FADE + "\n" + HARD_KILL


def _big_line_too_long(markup, fmt):
    """Return the text of any big-text line that is too long for this
    format. These classes do not wrap, so a long line overflows the
    frame and is cut off (the failure that shipped in entry 3's first
    render). Limits come from the format's guardrails."""
    max_words, max_chars = guardrails.big_text_limits(fmt)
    classes = "|".join(guardrails.big_text_classes(fmt))
    # find each big-text div and measure its plain text
    for m in re.finditer(
            r'<div class="(?:' + classes + r')"[^>]*>(.*?)</div>',
            markup, re.DOTALL):
        inner = m.group(1)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars or len(text.split()) > max_words:
            return text, max_words, max_chars
    return None


def validate_code(obj, fmt="shorts"):
    """Check one beat's scene code. Returns a list of problems.
    Runs on the timeline AFTER append_exit, so the hard kill is
    guaranteed present; validation here is about structure and syntax."""
    problems = []
    if not isinstance(obj, dict):
        return ["top level is not a JSON object"]
    markup = obj.get("markup")
    timeline = obj.get("timeline")
    if not isinstance(markup, str) or not markup.strip():
        problems.append("missing or empty 'markup'")
        return problems
    if not isinstance(timeline, str) or not timeline.strip():
        problems.append("missing or empty 'timeline'")
        return problems
    if markup.count("%%ID%%") < 1:
        problems.append("markup does not use the %%ID%% placeholder")
    if 'data-start="%%START%%"' not in markup:
        problems.append('markup is missing data-start="%%START%%"')
    if 'data-duration="%%DURATION%%"' not in markup:
        problems.append('markup is missing data-duration="%%DURATION%%"')
    if 'class="beat clip"' not in markup:
        problems.append('markup is missing class="beat clip"')
    if "<script" in markup.lower():
        problems.append("markup must not contain a <script> tag")
    if "<!--TIMELINE-->" in markup:
        problems.append("markup must not contain the <!--TIMELINE--> marker")
    # any placeholder other than the three allowed ones is a leftover
    leftovers = set(re.findall(r"%%([A-Z_]+)%%", markup))
    bad = leftovers - {"ID", "START", "DURATION"}
    if bad:
        problems.append(f"markup has unfilled placeholders: {sorted(bad)}")
    # big text lines do not wrap; a long one is cut off at the frame edge
    too_long = _big_line_too_long(markup, fmt)
    if too_long:
        text, max_words, max_chars = too_long
        problems.append(
            f"a big text line is too long and will be cut off: "
            f"{text[:40]!r} (max {max_words} words / {max_chars} chars "
            "per line; break it into multiple short lines)")
    # CSS check: measure the actual rendered width of every text line
    # from the stylesheet and flag any that would run off the frame.
    # The word-count rule above is a proxy; this is the real check,
    # and it catches long titles and labels too, not just big text.
    problems.extend(css_check.check_markup(markup, fmt))
    # the hard kill must be present (append_exit guarantees it; if the
    # writer wrote a timeline that already ends with it, it is kept)
    if HARD_KILL not in timeline:
        problems.append("timeline is missing the hard kill "
                        'tl.set("#%%ID%%", { opacity: 0 }, E)')
    err = _js_syntax_ok(timeline)
    if err:
        problems.append(f"timeline has a JS syntax error: {err}")
    return problems


def estimate_seconds(beat, script):
    """Rough beat length from its word count, ~2.25 words/sec. Used
    when writing a beat's code, to pace the animation to the time the
    narration actually takes. The real boundaries come from the
    whisper word timings at render time; this is only a pacing guide."""
    sentences = split_sentences(script)
    words = sum(len(sentences[n].split()) for n in beat["sentences"])
    return words / 2.25 + 0.8


def split_sentences(script):
    """Split a narration script into its sentences."""
    parts = re.split(r"(?<=[.!?])\s+", script.strip())
    return [p for p in parts if p]


def stored_code_is_fresh(script_obj, fmt="shorts"):
    """Check whether the scene code already stored in a script is
    current and valid, without calling any model. Returns a list of
    problems (empty means fresh). A missing or older codegen version
    is a problem, and so is any beat whose stored code fails the same
    validation the writer's output must pass (including the CSS check
    that measures real text widths)."""
    problems = []
    stored = script_obj.get("codegen_version", 0)
    if stored < CODEGEN_VERSION:
        problems.append(
            f"scene code is version {stored}, current is "
            f"{CODEGEN_VERSION}; the validation rules have changed "
            "since this code was written")
    code = script_obj.get("code")
    if not code:
        problems.append("script has no scene code")
        return problems
    beats = script_obj.get("beats", [])
    if len(code) != len(beats):
        problems.append(
            f"scene code has {len(code)} beats but the script has "
            f"{len(beats)}")
        return problems
    for i, entry in enumerate(code):
        beat_problems = validate_code(entry, fmt)
        if beat_problems:
            problems.append(
                f"beat {i + 1} stored code fails validation: "
                + "; ".join(beat_problems))
    return problems
