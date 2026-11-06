# OpenClipart + FreeSVG — build log (2026-11-06)

Curated subset for the ink-paper asset pack. CC0 only. Built by the
openclipart-freesvg library worker; do not push to GitHub (coordinator owns
the merge + Drive sync).

## Download route (verified live 2026-11-06)

- **OpenClipart JSON API is dead**: `https://openclipart.org/search/json/?query=…`
  302-redirects to the homepage. Use HTML search instead:
  `https://openclipart.org/search/?query=<q>&p=<n>` (pagination param is `p=`,
  not `page=`; results are relevance-sorted). Detail page
  `/detail/<id>/<slug>` carries JSON-LD (author, title, licence) and `/tag/…`
  links. SVG: `https://openclipart.org/download/<id>` (302s to the file).
- **FreeSVG**: search `https://freesvg.org/search?q=<q>&sort=downloads&page=<n>`,
  detail `https://freesvg.org/<slug>`, SVG
  `https://freesvg.org/download/<numeric-id>` — needs a browser User-Agent +
  Referer + session cookie, returns `application/octet-stream`. Detail pages
  list the author (usually just "OpenClipart") and related tags.
- 110 queries across 10 categories, top results per query (relevance on OC,
  most-downloaded on FreeSVG). Polite: 6 workers, ~0.2 s jitter, 3 retries.
  No rate-limiting encountered.

## Result

- **Kept: 1,215** — OpenClipart 771, FreeSVG 444.
  Per category: landmarks 183, buildings 70, animals 234, vehicles 115,
  nature 121, artifacts 218, diagrams 71, food 62, symbols 68, people 73.
- **Considered: 1,926 candidates** (1,291 OC + 635 FS). Rejected 711:
  >2 MB file 131 · >4 gradients 180 · >12 distinct colours 141 ·
  >1,200 paths 85 · embedded raster (`<image>`/data:) 33 · bad/no viewBox 10 ·
  scripted SVG (`<script>`) 5 · text-only 7 · no paint after normalise 7 ·
  unparseable after normalise 0 · duplicate within same source 112 ·
  only-background 0 (counted under no-paint where applicable).
- **pd_issue: 0 found.** Detail pages were scanned for the librarians'
  `pd_issue` tag; none of the 1,291 OC candidates carried it. Title
  blocklist (logo/trademark/brand/photo/3D/adobe etc.) applied at search time.
- **Cross-library mirrors: 34 assets** list the twin in `duplicates_of`
  (same slug in both sources — FreeSVG mirrors OpenClipart). NOT deduped
  here, per instructions; merge step resolves them.

## Normalisation (tools: /tmp/normalize.py, /tmp/harvest.py, /tmp/resume.py)

- Transparent background: full-frame rects stripped at any depth (34 files
  had a nested background rect; one, `sailing-ship`, rendered as a solid
  black block until this was fixed).
- Colours mapped by hue: black/grey → `{{ink}}`, warm hues → `{{red}}`,
  cool hues → `{{blue}}`, white fill → transparent (`none`), white stroke →
  `{{ink}}`. Implicit SVG defaults handled: bare paths get `{{ink}}`,
  stroked paths get `fill="none"`. Style-attribute colours and `url(#…)`
  fills (gradient first stop / `{{ink}}` for patterns) rewritten too.
- Gradients flattened (first stop), filters/patterns/masks removed,
  `stroke-linecap`/`stroke-linejoin` round, missing stroke-width set to 3%
  of viewBox max dimension, extreme widths clamped, ids prefixed with the
  asset slug and de-duplicated within the file, `width`/`height` dropped,
  `viewBox` kept (comma-separated viewBoxes repaired). Adobe `&ns_ai;`-style
  undefined entities substituted with their standard URIs.
- Every staged file re-parsed with a strict XML parser after normalising;
  all 1,215 parse, none contain raster/script, all contain a palette
  placeholder. Visual spot-check: 46-asset contact sheet rendered in
  headless Chrome on #f6f1e7 (see /tmp/sample-sheet2.png) — landmarks,
  animals, artifacts and diagrams read recognisably in ink/red/blue.
- `draw_on: yes` 445 / `no` 770. Style families: flat 845, silhouette 290,
  line 78, doodle 2. `has_text: true` on 31 files (labels kept as `<text>`).

## Known imperfections (kept anyway)

- A minority are dense photo-traced files (e.g. `spider-web`, single path
  with ~479 KB of coordinates) that read as a black mass at small size, and
  a few odd compositions (`radiant-cross-3` corner wedge,
  `deep-blue-sea-submarine`). They are usable at large size; a future
  visual-QC pass may cull them.
- Staged files are large: 126 MB total (avg ~100 KB, some detailed
  landmarks 0.5–2 MB of path data). A future SVGO/path-simplification pass
  could shrink them; not done — usability first.
- Rejected originals were deleted (599 files, 1.1 GB freed) so `sources/`
  holds only the originals of kept assets. `sources/` is now 129 MB.
- FreeSVG author is usually just "OpenClipart" (mirror); per-file author
  from the detail page is in the catalog where available.

## Files

- `catalog-openclipart-freesvg.json` — partial catalog, 1,215 entries
- `sources/openclipart/` + `sources/freesvg/` — untouched originals + LICENSE.md
- `staging/openclipart/` + `staging/freesvg/` — normalised `{{ink}}`/`{{red}}`/`{{blue}}` files
