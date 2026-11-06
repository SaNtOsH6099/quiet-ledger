# Open Peeps — licence snapshot

- **Library:** Open Peeps (https://www.openpeeps.com/)
- **Author:** Pablo Stanley
- **Source URL:** https://www.openpeeps.com/
- **Downloaded / assembled:** 2026-11-06
- **Licence:** CC0 1.0 Universal (public domain dedication)
- **Licence URL:** https://creativecommons.org/publicdomain/zero/1.0/
- **Attribution required:** No.

## Licence wording (from the homepage, 2026-11-06)

> "in under the CC0 License. This means you can copy, modify, distribute,
> remix, burn, and use the work, even for commercial purposes"

## CC0 1.0 — summary of the deed

"The person who associated a work with this deed has dedicated the work to the
public domain by waiving all of his or her rights to the work worldwide under
copyright law, including all related and neighboring rights, to the extent
allowed by law. You can copy, modify, distribute and perform the work, even
for commercial purposes, all without asking permission."

Full legal code: https://creativecommons.org/publicdomain/zero/1.0/legalcode

## Provenance of the parts in this folder

There is no official `pablostanley/open-peeps` GitHub repo (verified 404 on
2026-11-06) and the official download is a Gumroad bundle. The parts here
come from **react-peeps** (https://github.com/CeamKrier/react-peeps), a React
implementation of Open Peeps by Emre Çakır, cloned 2026-11-06 (commit at
clone time: master, depth 1). The artwork is Pablo Stanley's CC0 Open Peeps
design; the React wrapper code is MIT — see `react-peeps-LICENSE-MIT.md`
in this folder (copy of the repo's LICENSE file).

- `parts/<category>/<Name>.tsx` — original part files, untouched (174 parts:
  65 poses — 28 bust, 26 standing, 11 sitting; 51 hair; 33 faces;
  16 facial hair; 9 accessories). `None` (empty) variants were not copied.
- `parts-svg/<category>/<kebab>.svg` — the same parts converted from TSX/JSX
  to plain SVG fragments (ink `#1c1c1c`, paper `#f6f1e7`), for assembly.
  Conversion only: JSX expressions `{strokeColor || '#000000'}` /
  `{backgroundColor || '#FFFFFF'}` became the two house colours; no artwork
  was redrawn or altered.

Assembled figures (15–25) built from these parts live in
`assets/staging/open-peeps/`; the parts used per figure are listed in the
`notes` field of each `open-peeps:*` entry in `assets/catalog-people.json`.

## Note on the parts

Open Peeps parts are modular by design: a pose (body + arms + legs) plus a
head built from hair + face + facial hair + accessory, all positioned on a
shared canvas by the library's own layout (head at translate(225 0), face at
+159/186, facial hair at +123/338, accessory at +47/241). The assembly in
this pack replicates that layout exactly.
