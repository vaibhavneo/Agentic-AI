"""
Cross-Chart Strength Analysis
================================
Structured strength scoring across the Shodasavarga (16-varga) system —
Vargottama detection, Panchadha Maitri (five-fold planetary relationship),
Varga Vishwa Bala (per-chart dignity score), and Vimshopaka Bala (combined
weighted strength across multiple charts).

Source verification status (see also chart/divisional.py's module docstring
for the divisional-chart calculation formulas, which are separately and fully
verified against real reference charts):

- Panchadha Maitri methodology (natural + temporal relationship, combined into
  5 tiers) is standard, widely-attested classical methodology, cross-checked
  against the ingested "Comprehensive Prediction by Divisional Charts" (V.P.
  Goel) — including the specific methodological detail that Panchadha Maitri
  is computed ONCE from the D-1 chart and reused for dignity scoring in every
  divisional chart (not recomputed per-varga).
- Varga Vishwa Bala 0-20 scale (Own/Exaltation=20, Ati Mitra=18, Mitra=15,
  Neutral=10, Enemy=7, Bitter Enemy=5) is DIRECTLY CONFIRMED from Goel's book
  text extraction. The Debilitated tier's exact score was not confirmed by
  extraction (it plausibly shares the Bitter Enemy tier, but this is an
  ASSUMPTION — flagged below, not presented as certain).
- The per-varga Vimshopaka Bala WEIGHT TABLE (e.g. "D-1 is worth how many of
  the scheme's 20 points, D-9 how many, etc.") could NOT be recovered from
  Goel's book via text extraction — the table's numeric column did not survive
  PDF extraction, and visual PDF reading was not available in this session
  (poppler/Homebrew not installed). Rather than guess these numbers from
  training-data recall, this module uses an EQUAL-WEIGHTED fallback across the
  vargas relevant to a domain, clearly labeled via the `confidence` field
  returned by `vimshopaka_bala()`. Replace VIMSHOPAKA_WEIGHTS below with the
  real per-varga weights once confirmed (see chart/divisional.py header for
  the exact book/page to check), and flip DEFAULT_CONFIDENCE to "verified".
- Rahu/Ketu have no natural-friendship table in classical texts (they are
  shadow points, not physical grahas). This module follows the common
  practical convention of giving them the same natural relationships as
  Saturn — a documented simplification, not a sourced classical rule.
"""
from __future__ import annotations

from .calculator import Chart, EXALTATION, DEBILITATION, OWN_SIGNS, SIGN_LORDS
from .divisional import _get_dignity

PLANETS_9 = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

# ══════════════════════════════════════════════════════════════════════════
# Naisargika Maitri — natural (permanent) planetary relationships
# Standard classical table (BPHS), consistent across virtually all sources.
# Rahu/Ketu follow Saturn's relationships (documented convention, not a
# classical rule — see module docstring).
# ══════════════════════════════════════════════════════════════════════════

NAISARGIKA_MAITRI = {
    "Sun":     {"friend": ["Moon", "Mars", "Jupiter"], "enemy": ["Venus", "Saturn"]},
    "Moon":    {"friend": ["Sun", "Mercury"], "enemy": []},
    "Mars":    {"friend": ["Sun", "Moon", "Jupiter"], "enemy": ["Mercury"]},
    "Mercury": {"friend": ["Sun", "Venus"], "enemy": ["Moon"]},
    "Jupiter": {"friend": ["Sun", "Moon", "Mars"], "enemy": ["Mercury", "Venus"]},
    "Venus":   {"friend": ["Mercury", "Saturn"], "enemy": ["Sun", "Moon"]},
    "Saturn":  {"friend": ["Mercury", "Venus"], "enemy": ["Sun", "Moon", "Mars"]},
    "Rahu":    {"friend": ["Mercury", "Venus"], "enemy": ["Sun", "Moon", "Mars"]},   # = Saturn's
    "Ketu":    {"friend": ["Mercury", "Venus"], "enemy": ["Sun", "Moon", "Mars"]},   # = Saturn's
}


def _natural_relation(p1: str, p2: str) -> str:
    if p1 == p2:
        return "self"
    if p2 in NAISARGIKA_MAITRI[p1]["friend"]:
        return "friend"
    if p2 in NAISARGIKA_MAITRI[p1]["enemy"]:
        return "enemy"
    return "neutral"


def compute_temporal_maitri(d1: Chart) -> dict[str, dict[str, str]]:
    """Temporal (positional) friendship from D-1 sign distances.
    Houses 2,3,4,10,11,12 from a planet's sign = temporal friend.
    Houses 1,5,6,7,8,9 (i.e. same sign or the rest) = temporal enemy."""
    temporal: dict[str, dict[str, str]] = {}
    for p1 in PLANETS_9:
        if p1 not in d1.planets:
            continue
        temporal[p1] = {}
        s1 = d1.planets[p1].sign_index
        for p2 in PLANETS_9:
            if p2 not in d1.planets or p1 == p2:
                continue
            s2 = d1.planets[p2].sign_index
            distance = (s2 - s1) % 12 + 1   # 1-12
            temporal[p1][p2] = "friend" if distance in (2, 3, 4, 10, 11, 12) else "enemy"
    return temporal


def compute_panchadha_maitri(d1: Chart) -> dict[str, dict[str, str]]:
    """Five-fold relationship combining natural + temporal, computed once from
    D-1 and intended for reuse across every divisional chart (per classical
    methodology — see module docstring)."""
    temporal = compute_temporal_maitri(d1)
    result: dict[str, dict[str, str]] = {}
    for p1 in PLANETS_9:
        result[p1] = {}
        for p2 in PLANETS_9:
            if p1 == p2:
                result[p1][p2] = "self"
                continue
            nat = _natural_relation(p1, p2)
            tmp = temporal.get(p1, {}).get(p2)
            if tmp is None:
                result[p1][p2] = nat
                continue
            if nat == "friend" and tmp == "friend":
                result[p1][p2] = "great_friend"
            elif nat == "enemy" and tmp == "enemy":
                result[p1][p2] = "great_enemy"
            elif (nat == "friend" and tmp == "enemy") or (nat == "neutral" and tmp == "friend"):
                result[p1][p2] = "friend"
            elif (nat == "enemy" and tmp == "friend") or (nat == "neutral" and tmp == "enemy"):
                result[p1][p2] = "enemy"
            else:
                result[p1][p2] = "neutral"
    return result


# ══════════════════════════════════════════════════════════════════════════
# Varga Vishwa Bala — per-chart dignity score (0-20 scale, CONFIRMED from
# direct text extraction of Goel's book)
# ══════════════════════════════════════════════════════════════════════════

VARGA_VISHWA_BALA_SCALE = {
    "own_or_exalted": 20,
    "great_friend": 18,   # Ati Mitra
    "friend": 15,          # Mitra
    "neutral": 10,
    "enemy": 7,
    "great_enemy": 5,      # Bitter enemy (Ati Shatru)
    "debilitated": 5,      # ASSUMPTION: tied with great_enemy, not independently confirmed
}


def varga_vishwa_bala(planet: str, sign_idx: int, panchadha_maitri: dict[str, dict[str, str]]) -> int:
    """0-20 dignity score for `planet` placed in `sign_idx`, using the
    Panchadha Maitri relationships already computed from D-1."""
    if EXALTATION.get(planet) == sign_idx or sign_idx in OWN_SIGNS.get(planet, []):
        return VARGA_VISHWA_BALA_SCALE["own_or_exalted"]
    if DEBILITATION.get(planet) == sign_idx:
        return VARGA_VISHWA_BALA_SCALE["debilitated"]
    sign_lord = SIGN_LORDS[sign_idx]
    relation = panchadha_maitri.get(planet, {}).get(sign_lord, "neutral")
    if relation == "self":
        return VARGA_VISHWA_BALA_SCALE["own_or_exalted"]
    return VARGA_VISHWA_BALA_SCALE.get(relation, VARGA_VISHWA_BALA_SCALE["neutral"])


# ══════════════════════════════════════════════════════════════════════════
# Vargottama — same-sign strength across two charts. Classically the term
# names the D-1/D-9 case specifically; other same-sign pairs are labeled
# "cross-chart strength" rather than misusing the name.
# ══════════════════════════════════════════════════════════════════════════

def find_vargottama(d1: Chart, other: Chart) -> list[str]:
    """Planets occupying the same sign in both charts."""
    matches = []
    for name, p1 in d1.planets.items():
        p2 = other.planets.get(name)
        if p2 and p1.sign_index == p2.sign_index:
            matches.append(name)
    return matches


def find_all_vargottama(d1: Chart, divisional: dict[str, Chart]) -> dict[str, list[str]]:
    """Same-sign matches between D-1 and every divisional chart.
    Only the 'D9' entry is true classical Vargottama; other entries represent
    the general 'same sign in two charts = reinforced strength' technique."""
    return {key: find_vargottama(d1, chart) for key, chart in divisional.items()}


# ══════════════════════════════════════════════════════════════════════════
# Vimshopaka Bala — combined weighted strength across a group of vargas.
# WEIGHT TABLE IS AN EQUAL-WEIGHTED FALLBACK, not the real classical weights.
# See module docstring for why, and where to get the real numbers.
# ══════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIDENCE = "approximate"   # flip to "verified" once real weights are confirmed

# Shodasavarga group membership (all 16), used to build an equal-weighted
# scheme when real per-varga weights aren't available. Each chart in the
# scheme gets weight = 20 / len(scheme).
SHODASAVARGA = ["D1", "D2", "D3", "D4", "D7", "D9", "D10", "D12",
                 "D16", "D20", "D24", "D27", "D30", "D40", "D45", "D60"]


def vimshopaka_bala(
    planet: str,
    d1: Chart,
    divisional: dict[str, Chart],
    charts_in_scheme: list[str] | None = None,
    panchadha_maitri: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Combined weighted strength for `planet` across the given scheme of
    vargas (defaults to the full Shodasavarga). Returns a dict with the score
    (0-20), a confidence flag, and the per-chart breakdown."""
    scheme = charts_in_scheme or SHODASAVARGA
    scheme = [k for k in scheme if k == "D1" or k in divisional]
    if not scheme:
        return {"score": 0.0, "confidence": DEFAULT_CONFIDENCE, "breakdown": {}}

    maitri = panchadha_maitri or compute_panchadha_maitri(d1)
    chart_weight = 20.0 / len(scheme)   # equal-weighted fallback

    breakdown = {}
    total = 0.0
    for key in scheme:
        chart = d1 if key == "D1" else divisional[key]
        p = chart.planets.get(planet)
        if p is None:
            continue
        vishwa_bala = varga_vishwa_bala(planet, p.sign_index, maitri)
        varga_score = (chart_weight * vishwa_bala) / 20.0
        breakdown[key] = {"sign": p.sign, "vishwa_bala": vishwa_bala, "score": round(varga_score, 2)}
        total += varga_score

    return {
        "score": round(total, 2),
        "max_score": 20.0,
        "confidence": DEFAULT_CONFIDENCE,
        "breakdown": breakdown,
    }


# ══════════════════════════════════════════════════════════════════════════
# Human-readable strength summary — the concrete mechanism for feeding the
# LLM computed strength rather than raw undifferentiated chart data.
# ══════════════════════════════════════════════════════════════════════════

def strength_summary(
    planet: str,
    d1: Chart,
    divisional: dict[str, Chart],
    domain: str,
    varga_authority: dict | None = None,
) -> str:
    """Build a one-line computed-strength summary for `planet`, emphasizing
    the vargas authoritative for `domain` (via knowledge/varga_authority.py)."""
    from knowledge.varga_authority import get_authority

    authority = varga_authority or get_authority(domain)
    relevant = authority.get("primary", ["D1"]) + authority.get("secondary", [])
    relevant = [k for k in dict.fromkeys(relevant) if k == "D1" or k in divisional]  # dedupe, preserve order

    maitri = compute_panchadha_maitri(d1)

    placements = []
    if "D1" in relevant and planet in d1.planets:
        placements.append(f"{d1.planets[planet].dignity} in D-1 ({d1.planets[planet].sign})")
    for key in relevant:
        if key == "D1":
            continue
        chart = divisional.get(key)
        if chart is None or planet not in chart.planets:
            continue
        p = chart.planets[planet]
        placements.append(f"{p.dignity} in {key} ({p.sign})")

    vargottama_charts = [
        key for key in relevant if key != "D1" and key in divisional
        and planet in find_vargottama(d1, divisional[key])
    ]

    vb = vimshopaka_bala(planet, d1, divisional, charts_in_scheme=relevant, panchadha_maitri=maitri)

    parts = [planet]
    if vargottama_charts:
        label = "Vargottama" if vargottama_charts == ["D9"] else "same-sign strength"
        parts.append(f"is {label} ({', '.join(vargottama_charts)})")
    if placements:
        parts.append(", ".join(placements))
    confidence_note = "" if vb["confidence"] == "verified" else " [approximate weighting]"
    parts.append(f"Vimshopaka Bala ({domain}-relevant vargas): {vb['score']}/{vb['max_score']}{confidence_note}")

    return " — ".join(parts) if len(parts) <= 2 else f"{parts[0]} {'; '.join(parts[1:])}"
