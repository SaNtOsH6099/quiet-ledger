# Sync note — echoes-hyperframes-v2/tools

`build_captions_hormozi.py` here is byte-identical to the LOCAL builder
`~/workspace/video-tools/echoes-hyperframes/tools/build_captions_hormozi.py`
as of 2026-11-24 (verified by `diff` — no output). It carries the
lesson-41 pause audit (TEST 1/2/2b, behind `--mix`) and the lesson-43
check 6 (no duplicate starts / same-frame pops), which the v1 repo
builder does NOT have (v1 last committed 2026-11-17T07:52:42Z).

`build_captions.py` (legacy) and `render_captions_24fps.sh` are
identical to local AND to v1 (diff exit 0 on both).

`caption_checks.py` (new, 2026-11-24) is the shared module for the
token-level caption guards — lesson-88 (corrected two-tier: 0.13s
floor / 0.17s bar, with the documented-exception mechanism), lesson-43,
0.8s floor, G0 first-word-at-0.00, keyword cap (max 4, target 3),
width assert (Archivo Black, 810px box, max 2 lines), fragment and
overlap checks. Both builders and the grouping helper
(group_phrases.py) import it, so all three measure the same way.
Synced local <-> draft the same way as the builders below.

Rule: whenever the local builder changes, re-copy it here and verify
with:

    diff echoes-hyperframes-v2/tools/build_captions_hormozi.py \
         ~/workspace/video-tools/echoes-hyperframes/tools/build_captions_hormozi.py \
    && echo SYNCED

A drift here is silent and expensive — it is exactly how v1 fell
behind (G2 in AUDIT.md). Do not edit the v2 copy in place; the local
builder is the source of truth.

## Drift 2026-11-24 — RESOLVED

SYNC.md's "byte-identical as of 2026-11-18" claim became false: the
corrected lesson-88 assert (0.13s floor / 0.17s bar) was edited into
the DRAFT copy in place (fa4f6394799765551d5b84dbf8bfec29) and local
(e35c44aedaa434edc6a4466ad0447d95, old 2-frame assert) was never
updated; GitHub matched local (old assert). Resolved 2026-11-24 by
the caption-tooling build: BOTH copies now import the shared
caption_checks.py, which carries the corrected assert (plus the
documented-exception mechanism), and the lesson-88 check runs AFTER
the pause audit in both copies (the draft's corrected order). Local
is the source of truth again; the draft's in-place edit is superseded
and no longer exists as inline code. Verified: local == draft on all
three files (build_captions.py 104b26e8, build_captions_hormozi.py
39eb4246, caption_checks.py 88ff64a6).
