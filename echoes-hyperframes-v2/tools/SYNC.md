# Sync note — echoes-hyperframes-v2/tools

`build_captions_hormozi.py` here is byte-identical to the LOCAL builder
`~/workspace/video-tools/echoes-hyperframes/tools/build_captions_hormozi.py`
as of 2026-11-18 (verified by `diff` — no output). It carries the
lesson-41 pause audit (TEST 1/2/2b, behind `--mix`) and the lesson-43
check 6 (no duplicate starts / same-frame pops), which the v1 repo
builder does NOT have (v1 last committed 2026-11-17T07:52:42Z).

`build_captions.py` (legacy) and `render_captions_24fps.sh` are
identical to local AND to v1 (diff exit 0 on both).

Rule: whenever the local builder changes, re-copy it here and verify
with:

    diff echoes-hyperframes-v2/tools/build_captions_hormozi.py \
         ~/workspace/video-tools/echoes-hyperframes/tools/build_captions_hormozi.py \
    && echo SYNCED

A drift here is silent and expensive — it is exactly how v1 fell
behind (G2 in AUDIT.md). Do not edit the v2 copy in place; the local
builder is the source of truth.
