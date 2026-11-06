"""Guardrails: the basic rules that keep the video from breaking.

rules.py loads config/guardrails.json (data, not code, so the control
app can change the rules later). css_check.py measures the rendered
width of the text from the stylesheet and flags lines that would run
off the frame.
"""
from pipeline.guardrails.rules import (  # noqa: F401
    BASIC_RULES,
    FORMATS,
    big_text_classes,
    big_text_limits,
    get,
)
