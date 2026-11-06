# Asset pack

Premade SVG objects for the code-drawn video pipeline, normalised to
the house palette (warm paper #f6f1e7, ink #1c1c1c, red #d9481f, blue
#2b5ea7). Every visual in a video is drawn in code; these are the
reusable objects, so only missing objects get hand-drawn.

- `catalog.json` is the source of truth: one entry per asset, with
  source, licence, category, tags, viewBox, and whether it draws on.
- Normalised SVGs live by category (`landmarks/`, `people/`,
  `animals/`, `vehicles/`, `nature/`, `artifacts/`, `diagrams/`,
  `food/`, `symbols/`, `scenes/`) and carry `{{ink}}`, `{{red}}`,
  `{{blue}}` placeholders — the palette is substituted at render time,
  never baked in. Backgrounds are transparent; the scene sets paper.
- `sources/` holds the original downloads, untouched, one folder per
  library, each with a LICENSE.md snapshot.
- `tools/` holds the pack tooling: `normalize.py` (SVG to normalised
  form), `dedup.py` (duplicate detection), `build-catalog.py`
  (validate the catalog, generate LICENSES.md and catalog.csv),
  `render-preview.py` (render assets on paper for visual QA),
  `palette-map.json` (source colours to house palette).
- `LICENSES.md` lists every library's licence and attribution.
  `CHANGELOG.md` is CalVer (YYYY.MM.patch). `WANTED.md` is the
  hand-drawing backlog: objects no library covers.

Licence rule: only CC0 / MIT / Apache-2.0 / ISC / CC-BY / CC-BY-SA
files are in this pack, with the licence recorded per file. unDraw,
ManyPixels and DrawKit are NOT in the pack — their licences forbid
redistributing assets in packs. This is not legal advice; re-check
each source's licence page before a public release.
