"""
Deterministic chart tools (Phase 5). Each function reads ONLY from an
already-built Chart Bundle dict and returns structured data - never prose,
never a recalculation. The AI model must call these (directly or via the
grounded context built from them) rather than inferring placements itself.
"""
from __future__ import annotations

from typing import Optional


def get_chart_metadata(bundle: dict) -> dict:
    return {
        "chart_id": bundle["chart_id"],
        "profile_name": bundle["profile_name"],
        "created_at": bundle["created_at"],
        "schema_version": bundle["schema_version"],
        "calculation_config": bundle["calculation_config"],
    }


def get_chart_summary(bundle: dict) -> dict:
    d1 = bundle["divisional_charts"].get("D1", {})
    return {
        "chart_id": bundle["chart_id"],
        "profile_name": bundle["profile_name"],
        "ascendant": d1.get("ascendant"),
        "current_mahadasha": bundle["timing"]["current_mahadasha"],
        "current_antardasha": bundle["timing"]["current_antardasha"],
    }


def get_ascendant(bundle: dict, division: str = "D1") -> Optional[dict]:
    chart = bundle["divisional_charts"].get(division.upper())
    return chart["ascendant"] if chart else None


def get_planet_position(bundle: dict, planet: str, division: str = "D1") -> Optional[dict]:
    chart = bundle["divisional_charts"].get(division.upper())
    if not chart:
        return None
    return chart["planets"].get(planet.title())


def get_house_details(bundle: dict, house_num: int, division: str = "D1") -> Optional[dict]:
    chart = bundle["divisional_charts"].get(division.upper())
    if not chart or not (1 <= house_num <= 12):
        return None
    sign_idx = (chart["ascendant"]["sign_index"] + house_num - 1) % 12
    lord = chart["house_lords"][house_num - 1]
    occupants = [name for name, p in chart["planets"].items() if p["house"] == house_num]
    return {"house": house_num, "sign_index": sign_idx, "lord": lord, "occupants": occupants}


def get_divisional_chart(bundle: dict, division: str) -> Optional[dict]:
    return bundle["divisional_charts"].get(division.upper())


def get_planet_across_divisions(bundle: dict, planet: str) -> dict:
    out = {}
    planet = planet.title()
    for div, chart in bundle["divisional_charts"].items():
        p = chart["planets"].get(planet)
        if p:
            out[div] = {"sign": p["sign"], "house": p["house"], "dignity": p["dignity"]}
    return out


def get_current_dasha(bundle: dict) -> dict:
    return bundle["timing"]


def get_dasha_sequence(bundle: dict) -> list:
    return bundle["timing"]["mahadasha_antardasha_sequence"]


def get_yogas(bundle: dict) -> dict:
    return bundle.get("derived", {}).get("yogas", {"note": "not populated in Milestone 1"})


def get_vargottama_planets(bundle: dict) -> dict:
    return bundle.get("derived", {}).get("vargottama", {})


def compare_d1_d9(bundle: dict) -> dict:
    d1 = bundle["divisional_charts"].get("D1", {})
    d9 = bundle["divisional_charts"].get("D9", {})
    comparison = {}
    for planet, p1 in d1.get("planets", {}).items():
        p9 = d9.get("planets", {}).get(planet) if d9 else None
        comparison[planet] = {
            "d1_sign": p1.get("sign"), "d1_house": p1.get("house"),
            "d9_sign": p9.get("sign") if p9 else None,
            "d9_house": p9.get("house") if p9 else None,
            "vargottama": bool(p9 and p1.get("sign") == p9.get("sign")),
        }
    return comparison


def retrieve_classical_sources(bundle: dict, topic: str) -> dict:
    return {"note": "classical-source retrieval is Phase 9, not implemented in Milestone 1",
            "topic": topic}
