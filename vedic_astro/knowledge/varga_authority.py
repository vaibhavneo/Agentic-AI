"""
Varga Authority Mapping
=========================
Which divisional charts are classically authoritative for which life domain.
Used by ChartContext.build_full_context(topic) to select/emphasize the right
vargas per domain, instead of feeding every domain the same undifferentiated
set of charts.

Keys match the exact `topic` strings already used in agents/prediction_engine.py
(analyze_career -> 'career', analyze_wealth -> 'wealth', analyze_relationships ->
'marriage', analyze_soul_purpose -> 'soul', analyze_life_lessons -> 'lessons').

D-1 is always implicitly primary for every domain (the birth chart is the base
promise every other varga refines) and is not repeated in each entry below.

Source: cross-referenced against DIVISIONAL_MEANINGS (this package) and the
domain-per-chapter organization of "Comprehensive Prediction by Divisional
Charts" (V.P. Goel) and "A Vedic Astrology Jyotish Primer" (Rohini Ranjan),
both already in the ingested knowledge base.
"""

VARGA_AUTHORITY = {
    "career": {
        "primary": ["D1", "D10"],
        "secondary": ["D9"],
    },
    "wealth": {
        "primary": ["D1", "D2"],
        "secondary": ["D9"],
    },
    "marriage": {
        "primary": ["D1", "D9"],
        "secondary": ["D7"],
    },
    "soul": {
        "primary": ["D1", "D20", "D24"],
        "secondary": ["D9"],
    },
    "lessons": {
        "primary": ["D1", "D30"],
        "secondary": [],
    },
    # Not yet wired to a dedicated analyze_*() function, but reserved for
    # any future "overall life" synthesis — D-60 is classically the single
    # most weighted chart for general life results.
    "general_life": {
        "primary": ["D1", "D60"],
        "secondary": ["D9"],
    },
}


def get_authority(topic: str) -> dict:
    """Return {'primary': [...], 'secondary': [...]} for a topic, defaulting
    to D-1 only (primary) if the topic isn't recognized."""
    return VARGA_AUTHORITY.get(topic, {"primary": ["D1"], "secondary": []})
