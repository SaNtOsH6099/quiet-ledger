# Asset Pack Changelog

CalVer: `YYYY.MM.patch`. The pack is `ink-paper-asset-pack`.

## 2026.11.0 — 2026-11-06 (initial pack)

**11,241 assets** from the 7 Tier 1 libraries, all normalised to the
house palette (paper #f6f1e7, ink #1c1c1c, red #d9481f, blue #2b5ea7)
with `{{ink}}` / `{{red}}` / `{{blue}}` / `{{paper}}` placeholders,
transparent backgrounds, and ids prefixed per asset.

| Library | Kept | Licence | Notes |
| --- | --- | --- | --- |
| Tabler | 5,193 | MIT | Outline icons in full (1,054 filled variants skipped — not stroke, cannot draw-on). |
| Lucide | 2,028 | ISC | Icons in full. |
| Kitbitz | 2,131 | CC0-1.0 | Hand-drawn objects; licence verified live (kitbitz.art FAQ: redistribution in packs explicitly allowed). 146 rejected (141 embedded raster, 2 oversize, 3 empty). |
| OpenClipart | 750 | CC0-1.0 | Curated subset. |
| FreeSVG | 419 | CC0-1.0 | Curated subset. |
| Open Doodles | 33 | CC0-1.0 | All 33 illustrations. |
| Open Peeps | 20 | CC0-1.0 | 20 figures assembled from 174 parts. |
| SVG Silh | 642 | CC0-1.0 | Curated silhouettes (1,709 of 2,351 candidates rejected). |
| Wikimedia Commons | 28 | mixed (see below) | Named landmarks, per-file licence check. |

**Dedup:** 194 cross-library duplicates removed (hash-based: exact +
normalised-SVG). 137 were Kitbitz colour variants that collapse to one
asset after palette normalisation (e.g. teal/blue variants both become
`{{blue}}`); 31 were OpenClipart/FreeSVG mirrors; the rest were
within-library duplicates. Losers are recorded in the winner's
`duplicates_of`. 297 path-data-only groups (same paths, different
viewBox/colours — e.g. Lucide circle/square variants) were kept as
distinct artwork.

**Licences:** per-file, in the catalog and in LICENSES.md. 10 Wikimedia
files need attribution (8 CC-BY-3.0, 2 CC-BY-SA-3.0: golden-gate-bridge,
burj-khalifa — the only share-alike files in the pack; recoloured
derivatives of those two stay SA). Everything else is CC0, MIT, ISC,
or public domain. No NC/ND, no unDraw / ManyPixels / DrawKit.

**Destination (Drive hybrid):** the catalog (`assets/catalog.json`)
lives in the repo, versioned. The asset SVG files live on Google Drive
under the quiet-ledger folder in `assets/` (mirroring categories), and
the resolver fetches only the assets a beat uses, at render time.
`pipeline/drive/sync_pack.py` + the `sync-pack` workflow upload the
pack (idempotent, md5 skip). The catalog's `file` field is the path
relative to the Drive `assets/` folder (e.g. `landmarks/eiffel-tower.svg`).

**Draw-on:** `draw_on: yes` on true-stroke assets (Tabler, Lucide,
most Kitbitz doodles, some OpenClipart/FreeSVG line art, 14 Wikimedia
landmarks). `draw_on: no` on filled/silhouette art (SVG Silh, Open
Doodles, Open Peeps, filled icons) — fade/scale instead.

**Merge QA drops (3):** `openclipart:deep-blue-sea-submarine` (abstract
composition, does not read as a submarine), `openclipart:radiant-cross-3`
(a corner fragment, does not read as a cross), `openclipart:tall-ship-1`
(opaque white background rect + black water mass, reads as a box, not a
ship). All three were flagged by the OpenClipart worker as known
imperfections and failed the phone-size render check at merge.

**Known imperfections (kept, for a future visual-QC cull):** a few dense
photo-traced OpenClipart files read as a black mass at small size
(e.g. `spider-web`, one 479 KB path). The `cn-tower` aspect
ratio is 0.09 (very tall/narrow — place at a small width).
`burj-khalifa` is a height-comparison diagram with metre labels
(`has_text`).
