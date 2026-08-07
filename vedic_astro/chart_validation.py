"""
Regex-based claim validation (Phase 6). Scans an LLM answer for two claim
types that are the most common and most consequential ways a model
hallucinates a chart detail even when the real data was in its context:

  1. Planet-in-Sign claims   ("Mars is in Leo", "Saturn sits in Aquarius")
  2. House-lord claims       ("Mars is the 5th lord", "the 10th lord is Saturn")

Both are checked against an already-built Chart Bundle dict — never against
a recalculation — so this module only ever compares text to the same ground
truth the model was given. It does not understand astrology; it is a
sanity net for facts that ARE explicitly present in the bundle.
"""
from __future__ import annotations

import re
from typing import Optional

PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

_PLANET_ALT = "|".join(PLANETS)
_SIGN_ALT = "|".join(SIGNS)

# "Mars is in Leo", "Saturn retrograde in Aquarius", "Venus occupies Taurus",
# "Mercury is placed/posited/situated in Gemini", "Sun transiting Cancer".
PLANET_SIGN_RE = re.compile(
    rf"\b(?P<planet>{_PLANET_ALT})\b"
    rf"(?:\s+(?:is|are|sits|lies))?(?:\s+currently)?(?:\s+retrograde)?(?:\s+\w+ly)?"
    rf"\s+(?:in|placed\s+in|posited\s+in|situated\s+in|occupies|occupying|transiting(?:\s+through)?)"
    rf"\s+(?:the\s+sign\s+of\s+|the\s+sign\s+)?"
    rf"(?P<sign>{_SIGN_ALT})\b",
    re.IGNORECASE,
)

_ORDINAL = r"\d+(?:st|nd|rd|th)"

# "Mars is the 5th lord", "Saturn rules the 10th house"
LORD_CLAIM_A_RE = re.compile(
    rf"\b(?P<planet>{_PLANET_ALT})\b\s+(?:is\s+(?:the\s+)?|rules\s+(?:the\s+)?)"
    rf"(?P<house>{_ORDINAL})\s+(?:lord|house lord|house)\b",
    re.IGNORECASE,
)

# "the 5th lord is Mars", "lord of the 10th house is Saturn"
LORD_CLAIM_B_RE = re.compile(
    rf"\b(?:the\s+)?(?:lord\s+of\s+(?:the\s+)?)?(?P<house>{_ORDINAL})\s+(?:house\s+)?lord\s+is\s+"
    rf"(?:the\s+planet\s+)?(?P<planet>{_PLANET_ALT})\b",
    re.IGNORECASE,
)


def _ordinal_to_int(ordinal: str) -> Optional[int]:
    digits = re.match(r"\d+", ordinal)
    if not digits:
        return None
    n = int(digits.group())
    return n if 1 <= n <= 12 else None


def extract_planet_sign_claims(text: str) -> list[dict]:
    """Every 'Planet is in Sign'-shaped claim found in free text."""
    claims = []
    for m in PLANET_SIGN_RE.finditer(text):
        claims.append({
            "type": "planet_sign",
            "planet": m.group("planet").title(),
            "claimed_sign": m.group("sign").title(),
            "matched_text": m.group(0),
        })
    return claims


def extract_house_lord_claims(text: str) -> list[dict]:
    """Every 'Planet is the Nth lord' / 'the Nth lord is Planet'-shaped claim.
    House lordships are always D-1-derived regardless of which divisional
    chart the surrounding conversation is about (see web/app.py's system
    prompt) — callers should always validate these against D-1."""
    claims = []
    seen_spans = set()
    for regex in (LORD_CLAIM_A_RE, LORD_CLAIM_B_RE):
        for m in regex.finditer(text):
            if m.span() in seen_spans:
                continue
            seen_spans.add(m.span())
            house = _ordinal_to_int(m.group("house"))
            if house is None:
                continue
            claims.append({
                "type": "house_lord",
                "planet": m.group("planet").title(),
                "claimed_house": house,
                "matched_text": m.group(0),
            })
    return claims


def _get_division(bundle: dict, division: str) -> Optional[dict]:
    return bundle.get("divisional_charts", {}).get(division.upper())


def validate_text(text: str, bundle: dict, division: str = "D1") -> dict:
    """Check every extractable claim in `text` against `bundle`.

    Returns:
      {
        "claims_checked": int,
        "all_valid": bool,
        "issues": [ {type, planet, claimed_..., actual_..., matched_text} ],
        "confirmed": [ ...same shape, claims that matched the bundle... ],
      }
    """
    issues: list[dict] = []
    confirmed: list[dict] = []

    div_chart = _get_division(bundle, division)
    for claim in extract_planet_sign_claims(text):
        planet_data = (div_chart or {}).get("planets", {}).get(claim["planet"])
        if planet_data is None:
            continue  # planet not present in this division's data — can't check
        actual_sign = planet_data.get("sign")
        record = {**claim, "division": division, "actual_sign": actual_sign}
        if actual_sign == claim["claimed_sign"]:
            confirmed.append(record)
        else:
            issues.append(record)

    d1 = _get_division(bundle, "D1")
    house_lords = (d1 or {}).get("house_lords", [])
    for claim in extract_house_lord_claims(text):
        idx = claim["claimed_house"] - 1
        if not (0 <= idx < len(house_lords)):
            continue
        actual_lord = house_lords[idx]
        record = {**claim, "division": "D1", "actual_lord": actual_lord}
        if actual_lord == claim["planet"]:
            confirmed.append(record)
        else:
            issues.append(record)

    return {
        "claims_checked": len(issues) + len(confirmed),
        "all_valid": len(issues) == 0,
        "issues": issues,
        "confirmed": confirmed,
    }
