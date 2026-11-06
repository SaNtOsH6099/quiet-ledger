"""Validate: check Muse-written scene code against the guardrails.

scene.py holds validate_code (one beat's markup + timeline),
append_exit (the exit fade + hard kill, added mechanically), and
stored_code_is_fresh (the whole script's code, version + validity).
It runs locally when the code is written, in the ingest job before
the script reaches Drive, and in the scenes job as a last check
before rendering.
"""
from pipeline.validate.scene import (  # noqa: F401
    CODEGEN_VERSION,
    append_exit,
    estimate_seconds,
    split_sentences,
    stored_code_is_fresh,
    validate_code,
)
