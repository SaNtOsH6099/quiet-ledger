#!/usr/bin/env python3
"""The real code writer: the brain writes the drawn scene for each beat.

No fixed templates. For every beat, the brain reads the beat's story
(its sentences and a short visual idea) plus the design system, and
writes the actual scene code from scratch: the HTML/SVG markup and the
GSAP timeline that animates it. Different scenes get different code
because the story is different. The five old fixed templates are
reference only now; they are not used at render time.

Input: script.json from draft.py (script + beats with "sentences" and
"idea"). Output: the same script.json with a "code" list added, one
entry per beat: {"markup": ..., "timeline": ...}.

Each beat's code is validated before it is accepted:
  - markup is one beat div with the %%ID%% / %%START%% / %%DURATION%%
    placeholders and no other placeholders left over.
  - timeline is GSAP JS that ends with the hard kill
    tl.set("#%%ID%%", { opacity: 0 }, E), and it parses under
    `node --check` (real JS syntax, not a guess).
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
figures, kinetic text, diagrams). No photos, no generated imagery,
nothing that is not drawn. Invent the visual approach that best serves
THIS scene; do not copy a fixed template.

DESIGN SYSTEM (the look):
- Canvas: 1080 wide x 1920 tall, vertical. All coordinates are in this space.
- Background: warm paper #f6f1e7 (already in the page; do not set a
  background in your beat).
- Ink: #1c1c1c. Red accent: #d9481f. Blue: #2b5ea7. Grey text: #8a8378.
  Muted: #5c564a.
- Font: Geist (sans-serif), weights 500, 600, 700, 800. Use the shared
  classes below when they fit, or inline styles.
- Shared CSS classes (already defined; use them, do not redefine):
  .eyebrow: small caps kicker, 34px, letter-spacing 10px, grey, centered.
  .hook-line: huge kinetic text, 116px, weight 800, centered,
    white-space nowrap. Wrap each word in <span class="w">word</span>,
    and add red for red words: <span class="w red">word</span>.
  .chart-title: 40px, weight 800, letter-spacing 6px, centered.
  .chart-sub: 30px, weight 500, grey, centered.
  .caption-line: 34px, weight 600, muted, italic, centered.
  .diagram-title: 44px, weight 800, letter-spacing 6px, centered.
  .close-line: 104px, weight 800, centered, white-space nowrap.
    Same .w spans as hook-line.
  .close-sub: 38px, weight 600, grey, centered.
  SVG text: .axis-label (28px, 600, grey), .month-label (28px, 600, grey,
    centered), .peak-label (44px, 800), .scale-label (30px, 600, grey),
    .note (28px, 500, grey, italic), .part-label (32px, 600, muted).
  .red: color #d9481f. .blue: color #2b5ea7.
- You may use inline styles and your own classes for elements these do
  not cover. Keep font sizes in the same range (body 28-34px, titles
  40-44px, big words 100-116px).

STRUCTURE (how a beat is built):
- Your markup is ONE div:
  <div id="%%ID%%" class="beat clip" data-start="%%START%%"
   data-duration="%%DURATION%%" data-track-index="N">...</div>
  Use the exact placeholders %%ID%%, %%START%%, %%DURATION%%.
  Set data-track-index to your beat number (1 for the first beat, and
  so on).
- Inside the div, use HTML (divs with the shared classes) and/or SVG
  (<svg width="1080" height="1920"
   style="position:absolute;inset:0;overflow:visible;">...</svg>).
  SVG coordinates are in the 1080x1920 space.
- Keep everything inside the canvas: left margin at least 40px, right
  edge at most 1040px, top at least 120px, bottom at most 1800px. Do
  not let text or shapes overflow the edges or overlap each other.
- Your timeline is GSAP JavaScript. Two variables are already defined:
  S (the beat's start time in seconds) and E (the beat's end time).
  tl is the GSAP timeline. Two helpers are available: prepDraw(path)
  (prepares an SVG path for a draw-on animation; returns its length)
  and dashLen(selector) (returns a path's length).
- Animate with tl.fromTo(...), tl.to(...), tl.set(...). Use ease
  "power2.inOut" or "power3.out". Stagger word-by-word builds with
  stagger 0.11.
- The beat starts hidden. Fade it in at S, for example:
  tl.fromTo("#%%ID%%", { opacity: 0 }, { opacity: 1, duration: 0.4 }, S);
- CRITICAL, the hard kill: your timeline MUST end with the exit fade
  and then the hard kill, in this order:
  tl.to("#%%ID%%", { opacity: 0, duration: 0.4 }, E - 0.4);
  tl.set("#%%ID%%", { opacity: 0 }, E);
  This guarantees the beat is hidden at its end. If you omit the hard
  kill, the video is broken.
- Do not reference any element id you did not define in your own
  markup. All ids must start with %%ID%%- (for example %%ID%%-line).
- Do not put a <script> tag in your markup. Do not use the
  <!--TIMELINE--> marker; markup and timeline are separate fields.

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
tl.fromTo("#%%ID%% .eyebrow", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.5 }, S + 0.15);
document.querySelectorAll("#%%ID%% .hook-line").forEach(function (line, li) {
  tl.fromTo(line.querySelectorAll(".w"), { x: 70, opacity: 0 }, { x: 0, opacity: 1, duration: 0.32, stagger: 0.11 }, S + 0.25 + li * 0.5);
});
var swooshLen = prepDraw(document.getElementById("%%ID%%-swoosh"));
tl.fromTo("#%%ID%%-swoosh", { strokeDashoffset: swooshLen, opacity: 0 }, { strokeDashoffset: 0, opacity: 1, duration: 0.5, ease: "power2.inOut" }, S + 1.9);
tl.to("#%%ID%%", { opacity: 0, duration: 0.4, ease: "power1.inOut" }, E - 0.4);
tl.set("#%%ID%%", { opacity: 0 }, E);

EXAMPLE (chart; copy the pattern, invent the content):
markup:
<div id="%%ID%%" class="beat clip" data-start="%%START%%" data-duration="%%DURATION%%" data-track-index="2">
  <div class="chart-title" style="top: 170px;">TEMPERATURE RISES</div>
  <div class="chart-sub" style="top: 235px;">summer heat, month by month</div>
  <svg width="1080" height="1920" style="position:absolute;inset:0;overflow:visible;">
    <polyline id="%%ID%%-line-0" class="series-line" data-dot="%%ID%%-dot-0" points="150,1100 400,900 650,700 900,500" fill="none" stroke="#d9481f" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" />
    <circle id="%%ID%%-dot-0" r="13" fill="#d9481f" stroke="#f6f1e7" stroke-width="4" cx="150" cy="1100" opacity="0" />
    <text id="%%ID%%-peak-0" class="peak-label" x="900" y="470" fill="#d9481f" opacity="0">30&deg;</text>
  </svg>
  <div class="caption-line" style="top: 1420px;">the hotter it gets, the taller it grows</div>
</div>
timeline:
tl.fromTo("#%%ID%%", { opacity: 0 }, { opacity: 1, duration: 0.4, ease: "power1.inOut" }, S);
tl.fromTo("#%%ID%% .chart-title", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.4 }, S + 0.1);
document.querySelectorAll("#%%ID%% .series-line").forEach(function (path, si) {
  var len = prepDraw(path);
  var dot = document.getElementById(path.getAttribute("data-dot"));
  var drawDur = Math.max(2, (E - S - 2) * 0.55);
  tl.fromTo(path, { strokeDashoffset: len }, { strokeDashoffset: 0, duration: drawDur, ease: "none",
    onUpdate: function () {
      var p = 1 - parseFloat(path.style.strokeDashoffset) / len;
      var pt = path.getPointAtLength(Math.max(0, p * len));
      dot.setAttribute("cx", pt.x); dot.setAttribute("cy", pt.y);
    } }, S + 0.4 + si * 1.4);
  tl.fromTo(dot, { opacity: 0 }, { opacity: 1, duration: 0.3 }, S + 0.5 + si * 1.4);
  tl.to(dot, { opacity: 0, duration: 0.3 }, S + 0.4 + si * 1.4 + drawDur);
  tl.set(dot, { opacity: 0 }, S + 0.4 + si * 1.4 + drawDur + 0.3);
  tl.fromTo("#%%ID%%-peak-" + si, { opacity: 0, scale: 0.7, transformOrigin: "0% 100%" }, { opacity: 1, scale: 1, duration: 0.4, ease: "back.out(2)" }, S + 0.4 + si * 1.4 + drawDur + 0.2);
});
tl.fromTo("#%%ID%% .caption-line", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.5 }, E - 3.5);
tl.to("#%%ID%%", { opacity: 0, duration: 0.4, ease: "power1.inOut" }, E - 0.4);
tl.set("#%%ID%%", { opacity: 0 }, E);
'''


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
time: build, hold, then exit. Do not rush; do not leave dead air.

Return ONLY a JSON object with this exact shape:
{{
  "markup": "<div id=\\"%%ID%%\\" class=\\"beat clip\\" ...>...</div>",
  "timeline": "tl.fromTo(...); ... tl.set(\\"#%%ID%%\\", {{ opacity: 0 }}, E);"
}}

Rules:
- "markup" is one beat div, exactly as specified above.
- "timeline" is GSAP JavaScript using S and E, ending with the hard kill.
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


def validate_code(obj):
    """Check one beat's generated code. Returns a list of problems."""
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
    # the hard kill must be present, and it must come after an exit fade
    kill = 'tl.set("#%%ID%%", { opacity: 0 }, E)'
    if kill not in timeline:
        problems.append("timeline is missing the hard kill "
                        'tl.set("#%%ID%%", { opacity: 0 }, E)')
    if 'tl.to("#%%ID%%", { opacity: 0' not in timeline:
        problems.append("timeline is missing the exit fade to opacity 0")
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
            validate_code,
            f"code for beat {beat_no}",
        )
        code.append({"markup": obj["markup"], "timeline": obj["timeline"]})
        print(f"  beat {beat_no} code written via {provider}", flush=True)
    return code


def main():
    if len(sys.argv) < 3:
        print("usage: codegen.py SCRIPT_JSON OUT_DIR", file=sys.stderr)
        return 2
    script_path, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    script_obj = json.load(open(script_path))
    if "beats" not in script_obj or "script" not in script_obj:
        print("script.json has no script/beats; run draft.py first",
              file=sys.stderr)
        return 2
    code = codegen(script_obj)
    script_obj["code"] = code
    with open(os.path.join(out_dir, "script.json"), "w") as f:
        json.dump(script_obj, f, indent=2)
    print(f"code written for {len(code)} beats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
