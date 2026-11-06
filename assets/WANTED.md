# WANTED — asset gaps

Gaps in the pack, prioritised. Anything with no match gets hand-drawn
(in the house ink style, licensed CC0, into `sources/hand-drawn/`) and
logged here. Only adding a whole new library gets flagged to the user;
individual gaps are filled in batches.

## Named landmarks — no canonical free line-art source exists

Wikimedia Commons was searched per file (2026-11-06); these 16 could
not be sourced as clean line drawings. Each note is what was found, so
the next attempt does not repeat the search.

- **Taj Mahal** — only a 1.1 MB / 3,242-path stipple engraving (too
  detailed) plus a jali-pattern sheet.
- **Machu Picchu** — maps only.
- **Petra / Treasury** — no drawing.
- **Mount Fuji** — emblems/logos only.
- **Kilimanjaro** — maps/diagrams only.
- **Grand Canyon** — the one SVG is a blue park-boundary map blob.
- **Niagara Falls** — maps/coats of arms only.
- **Stonehenge** — one candidate is a land-parcel map, the other a 3D
  stone-joint diagram.
- **Hagia Sophia** — only a pink cutaway/segment diagram.
- **St Peter's Basilica** — floor plan only.
- **Sagrada Familia** — a Barcelona district map.
- **Sydney Harbour Bridge** — tiny faint schematic.
- **Kremlin** — site plan with Portuguese labels.
- **Forbidden City** — no drawing.
- **White House** — logos/floor plans only.
- **Notre-Dame** — the only clean CC0 file is a 3D-style model whose
  palette mapping collapses it into an unreadable black mass
  (rejected after render QC).

Hand-draw these in the house ink style as mystery topics need them.
The Eiffel Tower (Wikimedia, CC0) is the reference for the style.

## People — historical figures in period dress

Kitbitz has almost no human figures (people = Ghost 1–4 + Witch).
Open Peeps covers generic modern figures only. Historical figures in
period dress (e.g. a Victorian detective, a Roman senator, a medieval
monk) have no free source — hand-draw as topics need them.

## Specific named artifacts

Named artifacts (a specific crown, a specific manuscript page, a
specific relic) have no free line-art source. Hand-draw as topics need
them; generic artifacts (sword, crown, scroll, key) are covered by
Kitbitz / OpenClipart / SVG Silh.

## Coherent multi-object scenes

No free source draws a coherent multi-object scene (a room, a street,
a ritual) in one consistent ink style. Scenes are assembled from
single objects in code; a hand-drawn scene is a gap when a beat needs
one.

## Future visual-QC cull (already in the pack, flagged)

- `openclipart:spider-web` — dense photo-traced file, reads as a black
  mass at small size (one 479 KB path).
- `openclipart:radiant-cross-3` — odd composition.
- `openclipart:deep-blue-sea-submarine` — odd composition.
- Re-check the Wikimedia licences via a live browser before any public
  release of the pack (they were verified via the MediaWiki API
  `extmetadata`, not the File: pages, because commons.wikimedia.org
  returns 403 in this environment).
