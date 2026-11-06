#!/usr/bin/env python3
"""Deterministic keyword/tag search over the asset catalog.

No LLM calls, no network, stdlib only. Scores each catalog entry
against the words in a beat's text:

  - exact tag match: 3 points per query word;
  - title word match: 2 points;
  - category match: 1 point.

Query words are expanded through a synonym map first, so "tower"
also matches a catalog entry tagged "landmark". Only entries with a
score above zero are returned, best first (ties broken by id, so
results are deterministic).

Usage:
  python3 -m pipeline.assets.retrieve "the tower grows taller"
"""
import json
import re
import sys

from pipeline.assets import catalog as catalog_mod

# Query word -> catalog concept. The catalog's tags/titles use the
# concept word; the beat text uses the everyday word.
SYNONYMS = {
    "tower": "landmark",
    "person": "people",
    "man": "people",
    "woman": "people",
    "ship": "vehicle",
    "boat": "vehicle",
    "tree": "nature",
    "mountain": "nature",
    "sun": "nature",
    "moon": "nature",
    "sword": "artifact",
    "scroll": "artifact",
    "book": "artifact",
    "key": "artifact",
    "map": "artifact",
    "castle": "landmark",
    "pyramid": "landmark",
    "church": "building",
    "house": "building",
    "cat": "animal",
    "dog": "animal",
    "bird": "animal",
    "snake": "animal",
    "arrow": "diagram",
    "chart": "diagram",
}

RESULT_KEYS = ("id", "title", "category", "style_family", "draw_on",
               "viewBox", "aspect_ratio")

# Function words carry no meaning for matching: without this, a
# query like "the tower grows taller" scores a playing-cards image
# (title words "the" and "in") as highly as a real tower. Filter
# them from the query so only content words score.
STOPWORDS = {
    "a", "an", "the", "in", "on", "of", "to", "and", "or", "is",
    "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "with", "for", "from", "by", "at", "as", "into", "over", "after",
    "before", "under", "between", "through", "during", "up", "down",
    "out", "off", "about", "into", "so", "then", "than", "too",
}


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if t not in STOPWORDS]


def search_assets(beat_text, limit=8):
    """Return the top `limit` catalog entries for a beat's text, as
    dicts with keys: id, title, category, style_family, draw_on,
    viewBox, aspect_ratio. Returns [] when there is no catalog yet."""
    data = catalog_mod.load_catalog()
    if not data:
        return []
    assets = data.get("assets", []) if isinstance(data, dict) else []
    query = set(_tokens(beat_text))
    # synonym expansion: the concept word scores the same as the
    # word that was actually written.
    query |= {SYNONYMS[t] for t in query if t in SYNONYMS}
    scored = []
    for entry in assets:
        if not isinstance(entry, dict):
            continue
        tags = {t.lower() for t in entry.get("tags", [])
                if isinstance(t, str)}
        title_words = set(_tokens(entry.get("title", "")))
        category = str(entry.get("category", "")).lower()
        # categories are plural ("landmarks", "artifacts") while the
        # query words and synonym targets are singular ("landmark",
        # "artifact"); compare against the singular too.
        category_singular = category[:-1] if category.endswith("s") \
            else category
        score = 0
        for word in query:
            if word in tags:
                score += 3
            elif word in title_words:
                score += 2
            elif word in (category, category_singular):
                score += 1
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1].get("id", "")))
    out = []
    for _score, entry in scored[:limit]:
        out.append({k: entry.get(k) for k in RESULT_KEYS})
    return out


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or \
        "the tower grows taller in summer"
    print(json.dumps(search_assets(text), indent=2))
