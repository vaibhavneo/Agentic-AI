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

import re
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

# Classical divisional-chart (varga) terminology -> division code. A question
# that names a varga directly ("what does my Navamsa show", "Pushkar
# Navamsha") should pull in that division's placements even when the
# division dropdown wasn't touched — the dropdown is a UI convenience for
# picking which chart the CONVERSATION is grounded in, not the only way a
# user can ask about a specific varga mid-conversation.
DIVISION_KEYWORDS: dict[str, str] = {
    "d1": "D1", "rasi chart": "D1", "rashi chart": "D1",
    "d2": "D2", "hora": "D2",
    "d3": "D3", "drekkana": "D3", "drekana": "D3", "drishkana": "D3",
    "d4": "D4", "chaturthamsa": "D4", "chaturthamsha": "D4",
    "d7": "D7", "saptamsa": "D7", "saptamsha": "D7",
    "d9": "D9", "navamsa": "D9", "navamsha": "D9",
    "pushkar navamsa": "D9", "pushkar navamsha": "D9",
    "d10": "D10", "dasamsa": "D10", "dasamsha": "D10",
    "dashamsa": "D10", "dashamsha": "D10",
    "d12": "D12", "dwadasamsa": "D12", "dwadashamsha": "D12",
    "d16": "D16", "shodasamsa": "D16", "shodashamsha": "D16",
    "d20": "D20", "vimsamsa": "D20", "vimshamsha": "D20",
    "d24": "D24", "chaturvimsamsa": "D24", "chaturvimshamsha": "D24", "siddhamsa": "D24",
    "d27": "D27", "bhamsa": "D27", "nakshatramsa": "D27", "saptavimshamsha": "D27",
    "d30": "D30", "trimsamsa": "D30", "trimshamsha": "D30",
    "d40": "D40", "khavedamsa": "D40", "khavedamsha": "D40",
    "d45": "D45", "akshavedamsa": "D45", "akshavedamsha": "D45",
    "d60": "D60", "shashtiamsa": "D60", "shashtyamsha": "D60",
}


def detect_topics(question: str) -> list[str]:
    """Every topic whose keyword list matches somewhere in the question."""
    q = question.lower()
    return [topic for topic, keywords in TOPIC_KEYWORDS.items()
            if any(kw in q for kw in keywords)]


def detect_divisions(question: str) -> list[str]:
    """Every division named directly in the question (deduplicated). Uses
    word-boundary matching so 'd1' doesn't false-match inside 'd10'/'d12'."""
    q = question.lower()
    found: list[str] = []
    for keyword, div_code in DIVISION_KEYWORDS.items():
        if div_code not in found and re.search(rf"\b{re.escape(keyword)}\b", q):
            found.append(div_code)
    return found


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


def _format_full_division(bundle: dict, division_code: str) -> Optional[str]:
    """Full ascendant + planet placements for a division, for when the
    question names a varga directly rather than (or in addition to) a
    life-domain topic."""
    chart = tools.get_divisional_chart(bundle, division_code)
    if not chart:
        return None
    lines = [f"Ascendant: {chart['ascendant']['sign']}"]
    for name, p in chart["planets"].items():
        retro = " (retrograde)" if p.get("retrograde") else ""
        lines.append(f"{name}: {p['sign']} House {p['house']}{retro}, dignity {p['dignity']}")
    return "\n".join(f"- {l}" for l in lines)


def build_context_pack(question: str, bundle: dict, division: str = "D1") -> dict:
    """Detects topic(s) and named division(s) in `question` and assembles a
    fact block for each.

    Returns:
      {"topics": [...], "divisions_detected": [...],
       "context": "<text to append to the system prompt, or ''>"}
    """
    topics = detect_topics(question)
    divisions_detected = detect_divisions(question)

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

    # A varga named directly in the question (e.g. "Navamsa", "Pushkar
    # Navamsha", "Dasamsa") pulls in that division's full placements
    # regardless of domain-topic detection above and regardless of the
    # currently-selected `division` — a question can name a varga without
    # being classifiable as career/wealth/marriage/etc., and the user may
    # ask about a varga without switching the division dropdown to it.
    for div_code in divisions_detected:
        if div_code == division:
            continue  # already shown by the caller's own division block
        block = _format_full_division(bundle, div_code)
        if block:
            sections.append(f"## {div_code} placements (named in the question)\n{block}")

    return {
        "topics": topics,
        "divisions_detected": divisions_detected,
        "context": "\n\n".join(sections),
    }
