#!/usr/bin/env python3
"""The real code writer: the brain writes the drawn scene for each beat.

No fixed templates. For every beat, the brain reads the beat's story
(its sentences and a short visual idea) plus the design system, and
writes the actual scene code from scratch: the HTML/SVG markup and the
GSAP timeline that animates it. Different scenes get different code
because the story is different. The five old fixed templates are
reference only now; they are not used at render time.

Two things are done for the brain, not asked of it, because asking
failed in testing (run 42167255930: the brain wrote real code but
systematically omitted the exit, and the long prompt burned Groq's
token budget on retries):
  - The prompt is kept short (one compact example, not two long ones),
    so one beat's call fits comfortably in the free token budget.
  - The exit fade and hard kill are appended mechanically after the
    brain returns the timeline, so a beat can never ship without them.

Input: script.json from draft.py (script + beats with "sentences" and
"idea"). Output: the same script.json with a "code" list added, one
entry per beat: {"markup": ..., "timeline": ...}.

Each beat's code is validated before it is accepted:
  - markup is one beat div with the %%ID%% / %%START%% / %%DURATION%%
    placeholders and no other placeholders left over.
  - timeline is GSAP JS that parses under `node --check` (real JS
    syntax, not a guess) and ends with the hard kill (appended above).
A beat that fails validation is retried by the brain rotation; a beat
that cannot be written fails the draft instead of shipping bad code.

Stdlib only, except node for the JS syntax check. Keys come from the
environment, never from files. Reuses draft.generate for the brain
rotation (Groq -> Gemini -> NVIDIA -> local).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from draft import generate, split_sentences  # noqa: E402

DESIGN_SYSTEM = '''You write the drawn scene for one beat of a narrated
explainer. Every scene is drawn in code (line drawings, charts, stick
figures, kinetic text, diagrams). No photos, no generated imagery.
Invent the visual approach that best serves THIS scene.

CANVAS AND LOOK:
- 1080 wide x 1920 tall, vertical. All coordinates are in this space.
- Background is warm paper #f6f1e7 (already in the page; do not set one).
- Ink #1c1c1c, red accent #d9481f, blue #2b5ea7, grey text #8a8378.
- Font Geist, weights 500/600/700/800. Shared classes (use them, do
  not redefine): .eyebrow (34px caps kicker, grey), .hook-line (116px
  weight 800, centred; wrap each word in <span class="w">word</span>,
  red words get <span class="w red">), .chart-title (40px, 800),
  .chart-sub (30px, grey), .caption-line (34px, muted, italic),
  .diagram-title (44px, 800), .close-line (104px, 800; same .w spans),
  .close-sub (38px, grey). SVG text: .axis-label, .month-label,
  .peak-label (44px, 800), .scale-label, .note, .part-label.
- BIG TEXT RULE: .hook-line and .close-line do NOT wrap. One line
  holds at most 3 short words (about 20 characters). A full sentence
  on one line overflows the frame and is cut off. Break long text
  into MULTIPLE short lines, one .hook-line or .close-line div per
  phrase, stacked vertically. Never put a whole sentence on one big
  text line.
- Inline styles are fine for anything these do not cover. Body text
  28-34px, titles 40-44px, big words 100-116px.

STRUCTURE:
- Markup is ONE div:
  <div id="%%ID%%" class="beat clip" data-start="%%START%%"
   data-duration="%%DURATION%%" data-track-index="N">...</div>
  Use the exact placeholders %%ID%%, %%START%%, %%DURATION%%.
  data-track-index is your beat number (1 for the first beat).
- Inside, use HTML divs and/or one SVG
  (<svg width="1080" height="1920"
   style="position:absolute;inset:0;overflow:visible;">).
- Keep everything inside the canvas: left margin 40px, right edge
  1040px, top 120px, bottom 1800px. No overflow, no overlap.
- Timeline is GSAP JS. S is the beat start, E the beat end, tl the
  timeline. Helpers: prepDraw(path) readies an SVG path for draw-on
  (returns its length); dashLen(selector) returns a path length.
- Use ONLY core GSAP (tl.fromTo, tl.to, tl.set). Do NOT use motionPath,
  ScrollTrigger, or any other plugin; they are not loaded and the check
  fails. To move a dot along a path, draw the path with prepDraw and
  move the dot in onUpdate with path.getPointAtLength.
- Only call prepDraw or dashLen on paths, lines, polylines, circles.
  Never on <text> elements: text has no length, so fade it in with
  opacity instead of drawing it on.
- Never compute a tween duration from S or E as an absolute time
  (for example 14.6 - (S + 2.8)). Use a fixed number of seconds, or a
  relative length such as (E - S - 2).
- Animate with tl.fromTo / tl.to / tl.set, ease "power2.inOut" or
  "power3.out". Stagger word builds with stagger 0.11.
- Fade the beat in at S. Do NOT write the exit: the exit fade and the
  hard kill are added for you. Just animate the scene itself.
- Do not reference an id you did not define. All ids start with %%ID%%-.
- No <script> tag in markup. No <!--TIMELINE--> marker.

EXAMPLE (kinetic hook; copy the pattern, invent the content):
markup:
<div id="%%ID%%" class="beat clip" data-start="%%START%%" data-duration="%%DURATION%%" data-track-index="1">
  <div class="eyebrow" style="top: 470px;">A SURPRISING FACT</div>
  <div class="hook-line" style="top: 660px;"><span class="w">WHY</span> <span class="w red">TALLER?</span></div>
  <svg width="1080" height="1920" style="position:absolute;inset:0;overflow:visible;">
    <path id="%%ID%%-swoosh" d="M 330 810 C 480 840, 620 840, 760 805" fill="none" stroke="#d9481f" stroke-width="10" stroke-linecap="round" opacity="0" />
  </svg>
</div>
timeline:
tl.fromTo("#%%ID%%", { opacity: 0 }, { opacity: 1, duration: 0.4 }, S);
tl.fromTo("#%%ID%% .eyebrow", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.5 }, S + 0.15);
document.querySelectorAll("#%%ID%% .hook-line").forEach(function (line, li) {
  tl.fromTo(line.querySelectorAll(".w"), { x: 70, opacity: 0 }, { x: 0, opacity: 1, duration: 0.32, stagger: 0.11 }, S + 0.25 + li * 0.5);
});
var swooshLen = prepDraw(document.getElementById("%%ID%%-swoosh"));
tl.fromTo("#%%ID%%-swoosh", { strokeDashoffset: swooshLen, opacity: 0 }, { strokeDashoffset: 0, opacity: 1, duration: 0.5, ease: "power2.inOut" }, S + 1.9);
'''

# The exit every beat gets, appended mechanically (see module docstring).
EXIT_FADE = 'tl.to("#%%ID%%", { opacity: 0, duration: 0.4 }, E - 0.4);'
HARD_KILL = 'tl.set("#%%ID%%", { opacity: 0 }, E);'


def code_prompt(script, beat, beat_no, n_beats, est_seconds):
    """One beat's code-writing prompt."""
    sentences = split_sentences(script)
    spoken = " ".join(sentences[n] for n in beat["sentences"])
    role = ""
    if beat_no == 1:
        role = "This is the FIRST beat: the hook. It must stop a scroller. Big, bold, immediate."
    elif beat_no == n_beats:
        role = "This is the LAST beat: the closing. Quiet, one clear line, the thought that lingers."
    return f'''{DESIGN_SYSTEM}

YOUR BEAT (beat {beat_no} of {n_beats}):
{role}
The narration for this beat says: "{spoken}"
Visual idea: {beat["idea"]}
About {est_seconds:.1f} seconds long. Pace the animation to fill that
time: build, hold, then stop. Do not rush; do not leave dead air.

Return ONLY a JSON object with this exact shape:
{{
  "markup": "<div id=\\"%%ID%%\\" class=\\"beat clip\\" ...>...</div>",
  "timeline": "tl.fromTo(...); ..."
}}

Rules:
- "markup" is one beat div, exactly as specified above.
- "timeline" is GSAP JavaScript using S and E. Animate the scene only;
  do not write the exit, it is added for you.
- No em dashes. No markdown. No text outside the JSON object.
'''


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
    """Append the exit fade + hard kill if the brain omitted them.
    The hard kill is the guarantee the beat is hidden at E; without it
    the video is broken. Appending mechanically is reliable where
    asking the brain was not (it omitted them on every attempt)."""
    tl = timeline.rstrip()
    if HARD_KILL in tl:
        return tl
    # If the brain wrote its own exit fade but no hard kill, keep the
    # fade and just add the kill after it.
    if 'tl.to("#%%ID%%", { opacity: 0' in tl:
        return tl + "\n" + HARD_KILL
    return tl + "\n" + EXIT_FADE + "\n" + HARD_KILL


def _big_line_too_long(markup):
    """Return the text of any .hook-line / .close-line that is too long.
    These classes do not wrap, so a long line overflows the frame and
    is cut off (the failure that shipped in entry 3's first render).
    A line holds at most 4 words / 24 characters."""
    # find each big-text div and measure its plain text
    for m in re.finditer(
            r'<div class="(?:hook-line|close-line)"[^>]*>(.*?)</div>',
            markup, re.DOTALL):
        inner = m.group(1)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 24 or len(text.split()) > 4:
            return text
    return None


def validate_code(obj):
    """Check one beat's generated code. Returns a list of problems.
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
    long_line = _big_line_too_long(markup)
    if long_line:
        problems.append(
            f"a big text line is too long and will be cut off: "
            f"{long_line[:40]!r} (max 4 words / 24 chars per line; "
            "break it into multiple short lines)")
    # the hard kill must be present (append_exit guarantees it; if the
    # brain wrote a timeline that already ends with it, it is kept)
    if HARD_KILL not in timeline:
        problems.append("timeline is missing the hard kill "
                        'tl.set("#%%ID%%", { opacity: 0 }, E)')
    err = _js_syntax_ok(timeline)
    if err:
        problems.append(f"timeline has a JS syntax error: {err}")
    return problems


def estimate_seconds(beat, script):
    """Rough beat length from its word count, ~2.25 words/sec."""
    sentences = split_sentences(script)
    words = sum(len(sentences[n].split()) for n in beat["sentences"])
    return words / 2.25 + 0.8


def codegen(script_obj):
    """One brain call per beat. Returns the code list."""
    script = script_obj["script"]
    beats = script_obj["beats"]
    code = []
    for i, beat in enumerate(beats):
        beat_no = i + 1
        est = estimate_seconds(beat, script)
        obj, provider = generate(
            DESIGN_SYSTEM,
            code_prompt(script, beat, beat_no, len(beats), est),
            # validate on the timeline with the exit appended, so the
            # brain is judged on the scene, not on remembering the exit
            lambda o: validate_code({
                "markup": o.get("markup"),
                "timeline": append_exit(o.get("timeline", ""))
                if isinstance(o.get("timeline"), str) else o.get("timeline"),
            }),
            f"code for beat {beat_no}",
        )
        timeline = append_exit(obj["timeline"])
        code.append({"markup": obj["markup"], "timeline": timeline})
        print(f"  beat {beat_no} code written via {provider}", flush=True)
    return code


def main():
    if len(sys.argv) < 3:
        print("usage: codegen.py SCRIPT_JSON OUT_DIR [--regen]", file=sys.stderr)
        return 2
    script_path, out_dir = sys.argv[1], sys.argv[2]
    regen = "--regen" in sys.argv[3:]
    os.makedirs(out_dir, exist_ok=True)
    script_obj = json.load(open(script_path))
    if "beats" not in script_obj or "script" not in script_obj:
        print("script.json has no script/beats; run draft.py first",
              file=sys.stderr)
        return 2
    code = codegen(script_obj)
    script_obj["code"] = code
    if regen:
        # Count regenerations so the repair loop can stop after 3
        # instead of looping forever on a stubbornly bad layout.
        script_obj["code_regen_count"] = script_obj.get(
            "code_regen_count", 0) + 1
    with open(os.path.join(out_dir, "script.json"), "w") as f:
        json.dump(script_obj, f, indent=2)
    print(f"code written for {len(code)} beats")
    if regen:
        print(f"code_regen_count is now {script_obj['code_regen_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
