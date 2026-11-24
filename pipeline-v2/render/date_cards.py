#!/usr/bin/env python3
"""Inject Director-plan date cards into a generated Hormozi caption HTML
(text or plate variant), mirroring the caption pattern exactly.

A date card is a top-centre title card on a time jump (Director plan):
Anton 64px, top 180px, 3.0s from the shot's cut, fading in/out over
0.12s like the caption groups. The captions.json schema has NO
date-card entry type, and the v2 render consumes caption VIDEOS
(text + plate mp4s), so the cards live in the HyperFrames HTML, in
BOTH variants:
  - text variant: white text, same heavy black stroke + drop shadow as
    the captions, no plate (the plate lives in the other layer).
  - plate variant: text transparent, dark plate bar behind the card
    (same rgba(0,0,0,0.72) + border-radius + box-shadow spread as the
    word plates), so the multiply blend darkens the footage there.

Input file (date_cards.json, staged per video, optional):
  [{"text": "MARCH 1995", "start": 7.94},
   {"text": "AUGUST 1995", "start": 19.36, "end": 22.36}]
Each card needs "text" and "start"; "end" defaults to start + 3.0
("duration" is accepted as an alias for end - start).

Structure mirrors the generated captions:
  - div: class "clip datecard", data-start / data-duration /
    data-track-index (100+, a display lane only), inline font-size
    64px + top 180px, plain text (no word spans — the whole card
    fades as one unit).
  - CSS: a .datecard rule added to the <style> block
    (variant-dependent plate/text treatment), positioned like
    .caption (left 50px, width 980px, flex column, centred) but at
    top: 180px.
  - GSAP: fade-in fromTo (opacity 0 -> 1, 0.12s) at the card start
    and fade-out to (opacity 0, 0.12s) at end - 0.12, mirroring the
    caption group fade-outs. fromTo immediateRender holds the card
    invisible until its fade-in, exactly as the caption words are held.

Provenance: generalised from the 69 local injector
(work/inject_date_cards_69.py), which produced the HTML that passed
Gate 3 (all four cards verified rendering in the composite). The one
real bug that injector caught — inserting after the FIRST </div>
following a caption div nests the cards INSIDE the last caption
(because caption divs contain nested <div class="line"> elements) —
is preserved here as a depth-counted insertion plus a verification
assert (no caption div may open after the first card div).
`npm run check`'s nested_clip_never_visible warning is the catch for
it; the assert here fails the build before the render runs.

Usage as a module (echoes_captions_v2.py calls inject()):
  from date_cards import load, inject
  cards = load("in/date_cards.json")
  html = inject(html_text, cards)

Usage standalone (debugging a generated HTML):
  python3 date_cards.py <cards.json> <input.html> <output.html>
"""
import json
import sys

DURATION = 3.0
FADE = 0.12
TOP_PX = 180
SIZE_PX = 64

SHADOW = (
    "6px 0 0 #000, -6px 0 0 #000, 0 6px 0 #000, 0 -6px 0 #000,\n"
    "          6px 6px 0 #000, -6px -6px 0 #000, 6px -6px 0 #000, -6px 6px 0 #000,\n"
    "          0 10px 24px rgba(0, 0, 0, 0.95)"
)
PLATE = (
    "background: rgba(0, 0, 0, 0.72);\n"
    "        border-radius: 0.14em;\n"
    "        box-shadow: 0 0 0 0.10em rgba(0, 0, 0, 0.72);"
)


def load(path):
    """Read a date_cards.json file into [(text, start, end), ...].

    Validates: non-empty list, each card has text + start, text is
    ALL-CAPS (Anton cards are titles), starts strictly increasing,
    no two cards overlapping (a card's fade-out must finish before
    the next card's fade-in).
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list) or not raw:
        raise ValueError("date_cards.json must be a non-empty JSON list")
    cards = []
    for i, c in enumerate(raw):
        text = c.get("text", "")
        if not text or text != text.upper():
            raise ValueError(f"date card {i}: text must be non-empty ALL-CAPS: {text!r}")
        if "start" not in c:
            raise ValueError(f"date card {i}: missing 'start'")
        start = float(c["start"])
        if "end" in c:
            end = float(c["end"])
        elif "duration" in c:
            end = start + float(c["duration"])
        else:
            end = start + DURATION
        if end - start < 0.5:
            raise ValueError(f"date card {i}: duration {end - start:.2f}s, must be >= 0.5s")
        if start < 0:
            raise ValueError(f"date card {i}: negative start {start}")
        cards.append((text, start, end))
    for i in range(1, len(cards)):
        if cards[i][1] <= cards[i - 1][1]:
            raise ValueError("date cards must have strictly increasing starts")
        if cards[i][1] < cards[i - 1][2]:
            raise ValueError(
                f"date cards overlap: card {i} starts {cards[i][1]:.2f} "
                f"before card {i - 1} ends {cards[i - 1][2]:.2f}")
    return cards


def inject(html, cards):
    """Return html with the date cards injected. Refuses to run twice.
    Format-agnostic (Hormozi and legacy): the CSS anchor is the end
    of the <style> block, the div insertion is depth-counted from the
    last caption div, and the tweens go before the timeline
    registration — all of which exist in both compositions."""
    if "datecard" in html:
        raise ValueError("HTML already has date cards — refusing to inject twice")
    if "font-family: 'Anton'" not in html:
        raise ValueError(
            "no Anton @font-face in the HTML — the date cards specify "
            "Anton 64px and would render in the fallback font")
    n_caps = html.count('class="clip caption"')
    if n_caps < 1:
        raise ValueError("no caption divs found — is this a generated caption HTML?")

    plate_only = "background: #ffffff;" in html
    if not (plate_only or "background: #0a0a0a;" in html):
        raise ValueError("cannot detect variant from page background")

    # 1. CSS rule, at the end of the <style> block. (Was anchored on
    # the Hormozi .yl rule; the legacy composition has no .yl rule, so
    # the anchor is the format-agnostic </style>. .datecard is a
    # distinct class with no competing rules, so its position in the
    # block does not change rendering.)
    if plate_only:
        card_css = (
            "      .datecard {\n"
            "        position: absolute; left: 50px; width: 980px;\n"
            "        display: flex; flex-direction: column; align-items: center;\n"
            "        text-align: center;\n"
            "        font-family: \"Anton\", \"DejaVu Sans\", \"Arial Black\", sans-serif;\n"
            "        font-size: 64px; font-weight: 400; line-height: 1.05;\n"
            "        letter-spacing: 0.01em;\n"
            "        color: transparent;\n"
            "        text-shadow: none;\n"
            f"        {PLATE}\n"
            "      }\n"
        )
    else:
        card_css = (
            "      .datecard {\n"
            "        position: absolute; left: 50px; width: 980px;\n"
            "        display: flex; flex-direction: column; align-items: center;\n"
            "        text-align: center;\n"
            "        font-family: \"Anton\", \"DejaVu Sans\", \"Arial Black\", sans-serif;\n"
            "        font-size: 64px; font-weight: 400; line-height: 1.05;\n"
            "        letter-spacing: 0.01em;\n"
            "        color: #ffffff;\n"
            f"        text-shadow: {SHADOW};\n"
            "      }\n"
        )
    marker = "</style>"
    idx = html.index(marker)
    html = html[:idx] + card_css + html[idx:]

    # 2. Card divs, after the last caption div inside #root.
    # The caption divs contain nested <div class="line"> elements, so
    # the first </div> after a caption div's start closes a LINE, not
    # the caption div — inserting there nests the cards inside the last
    # caption (caught by `npm run check`: nested_clip_never_visible,
    # the cards would never appear). Count div depth from the last
    # caption div's opening tag until it returns to zero.
    last_cap = html.rindex('class="clip caption"')
    open_tag = html.rindex("<div", 0, last_cap)
    depth = 0
    i = open_tag
    div_end = None
    while i < len(html):
        if html.startswith("<div", i):
            depth += 1
            i += 4
        elif html.startswith("</div>", i):
            depth -= 1
            i += len("</div>")
            if depth == 0:
                div_end = i
                break
        else:
            i += 1
    if div_end is None:
        raise ValueError("could not find the end of the last caption div")
    divs = []
    for n, (text, start, end) in enumerate(cards):
        dur = round(end - start, 2)
        divs.append(
            f'      <div class="clip datecard" id="datecard{n}" '
            f'data-start="{start}" data-duration="{dur}" '
            f'data-track-index="{100 + n}" '
            f'style="font-size: {SIZE_PX}px; top: {TOP_PX}px;">{text}</div>'
        )
    html = html[:div_end] + "\n" + "\n".join(divs) + html[div_end:]

    # 3. GSAP tweens, before the window.__timelines registration.
    tweens = []
    for n, (text, start, end) in enumerate(cards):
        tweens.append(
            f'      tl.fromTo("#datecard{n}", {{opacity: 0}}, '
            f'{{opacity: 1, duration: {FADE}, ease: "power2.out"}}, {start:.2f});'
        )
        tweens.append(
            f'      tl.to("#datecard{n}", {{opacity: 0, duration: {FADE}}}, '
            f'{end - FADE:.2f});'
        )
    marker = '      window.__timelines = window.__timelines || {};'
    idx = html.index(marker)
    html = html[:idx] + "\n".join(tweens) + "\n" + html[idx:]

    # 4. Verify the injection.
    if html.count('class="clip datecard"') != len(cards):
        raise ValueError(f"expected {len(cards)} date-card divs")
    # The cards must be siblings of the caption divs inside #root, NOT
    # nested inside the last caption div (the nested_clip_never_visible
    # bug): no caption div may open after the first card div.
    first_card = html.index('class="clip datecard"')
    if 'class="clip caption"' in html[first_card:]:
        raise ValueError("date cards are nested inside a caption div — insertion point wrong")
    for n, (text, start, end) in enumerate(cards):
        if f'id="datecard{n}" data-start="{start}"' not in html:
            raise ValueError(f"card {n} div missing")
        if f'tl.fromTo("#datecard{n}"' not in html:
            raise ValueError(f"card {n} fade-in missing")
        if f'tl.to("#datecard{n}"' not in html:
            raise ValueError(f"card {n} fade-out missing")
        if text not in html:
            raise ValueError(f"card {n} text missing")
    return html


def main(argv):
    cards_path, inp, outp = argv[1], argv[2], argv[3]
    cards = load(cards_path)
    with open(inp, encoding="utf-8") as f:
        html = f.read()
    html = inject(html, cards)
    with open(outp, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {outp} ({len(cards)} date cards injected)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: date_cards.py <cards.json> <input.html> <output.html>")
    raise SystemExit(main(sys.argv))
