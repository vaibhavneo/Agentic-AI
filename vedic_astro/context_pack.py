"""
Keyword-based question topic detection (Phase 7). Looks at the user's
question, guesses which classical life-domain(s) it's about, and assembles
an extra block of house/planet facts — read only from an already-built
Chart Bundle via chart_tools, never recomputed — so the model gets the
specific facts a domain question needs even when they weren't already in
the base D-1 context (e.g. a wealth question surfaces the 2nd/11th houses
explicitly instead of relying on the model to remember them from a full
planet table).
"""
from __future__ import annotations

from typing import Optional

import chart_tools as tools

# topic -> keywords that suggest the question is about that domain.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "career": ["career", "job", "profession", "work", "promotion", "business",
               "boss", "employment", "occupation", "vocation"],
    "wealth": ["money", "wealth", "finance", "financial", "income", "rich",
               "property", "savings", "loan", "debt", "investment"],
    "marriage": ["marriage", "married", "marry", "spouse", "wife", "husband", "partner",
                 "relationship", "love", "divorce", "engagement", "wedding", "romance"],
    "children": ["children", "child", "kids", "pregnancy", "son", "daughter", "conceive"],
    "health": ["health", "illness", "disease", "surgery", "injury", "sick", "accident"],
    "education": ["education", "study", "studies", "exam", "degree", "college",
                  "school", "university", "student"],
    "spirituality": ["spiritual", "moksha", "meditation", "dharma", "soul purpose",
                     "enlightenment", "religion", "guru"],
    "travel": ["travel", "foreign", "abroad", "relocation", "immigration", "visa"],
    "timing": ["when", "timing", "which year", "which date", "dasha", "period", "transit"],
}

# topic -> houses classically significant to it (1-indexed).
TOPIC_HOUSES: dict[str, list[int]] = {
    "career": [10, 6, 1],
    "wealth": [2, 11],
    "marriage": [7, 8],
    "children": [5],
    "health": [1, 6, 8, 12],
    "education": [4, 5, 9],
    "spirituality": [9, 12, 5],
    "travel": [3, 9, 12],
    "timing": [],
}

# topic -> natural-significator planets worth surfacing.
TOPIC_KARAKAS: dict[str, list[str]] = {
    "career": ["Sun", "Saturn", "Mercury"],
    "wealth": ["Jupiter", "Venus"],
    "marriage": ["Venus", "Jupiter"],
    "children": ["Jupiter"],
    "health": ["Sun", "Mars", "Saturn"],
    "education": ["Mercury", "Jupiter"],
    "spirituality": ["Ketu", "Jupiter"],
    "travel": ["Rahu", "Moon"],
    "timing": [],
}

# topic -> divisional chart classically authoritative for it, when different from
# whatever division the conversation is already in.
TOPIC_DIVISION: dict[str, str] = {
    "career": "D10",
    "wealth": "D2",
    "marriage": "D9",
    "children": "D7",
}


def detect_topics(question: str) -> list[str]:
    """Every topic whose keyword list matches somewhere in the question."""
    q = question.lower()
    return [topic for topic, keywords in TOPIC_KEYWORDS.items()
            if any(kw in q for kw in keywords)]


def _format_house_fact(bundle: dict, house_num: int, division: str) -> Optional[str]:
    detail = tools.get_house_details(bundle, house_num, division)
    if not detail:
        return None
    occupants = ", ".join(detail["occupants"]) if detail["occupants"] else "no planets"
    return f"House {house_num} ({division}): lord {detail['lord']}, occupied by {occupants}"


def _format_planet_fact(bundle: dict, planet: str, division: str) -> Optional[str]:
    p = tools.get_planet_position(bundle, planet, division)
    if not p:
        return None
    retro = " (retrograde)" if p.get("retrograde") else ""
    return (f"{planet} ({division}): {p['sign']} House {p['house']}{retro}, "
            f"dignity {p['dignity']}, Nakshatra {p['nakshatra']} Pada {p['pada']}")


def build_context_pack(question: str, bundle: dict, division: str = "D1") -> dict:
    """Detects topic(s) in `question` and assembles a fact block for each.

    Returns:
      {"topics": [...], "context": "<text to append to the system prompt, or ''>"}
    """
    topics = detect_topics(question)
    if not topics:
        return {"topics": [], "context": ""}

    sections = []
    for topic in topics:
        topic_division = TOPIC_DIVISION.get(topic, division)
        facts = []
        for house_num in TOPIC_HOUSES.get(topic, []):
            fact = _format_house_fact(bundle, house_num, "D1")
            if fact:
                facts.append(fact)
        for planet in TOPIC_KARAKAS.get(topic, []):
            fact = _format_planet_fact(bundle, planet, topic_division)
            if fact:
                facts.append(fact)
        if topic_division != "D1":
            asc = tools.get_ascendant(bundle, topic_division)
            if asc:
                facts.append(f"{topic_division} Ascendant: {asc['sign']}")
        if facts:
            sections.append(f"## Relevant facts for '{topic}'\n" + "\n".join(f"- {f}" for f in facts))

    return {"topics": topics, "context": "\n\n".join(sections)}
