"""
Canonical Chart Bundle — the single authoritative, JSON-serializable
representation of a calculated horoscope. Built from the same Chart/
PlanetPosition objects the existing /api/chart route already computes;
this module formats and extends that data, it does not recalculate any
astronomical positions independently.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Optional

from chart.calculator import VIMSHOTTARI_SEQUENCE, VIMSHOTTARI_YEARS, NAKSHATRA_LORDS, SIGN_LORDS

SCHEMA_VERSION = "1.0"
CORE_DIVISIONS = {"D2", "D3", "D7", "D9", "D10"}


def _fingerprint(birth_info: dict) -> str:
    key = "{date}|{time}|{lat}|{lon}|{tz_offset}".format(
        date=birth_info.get("date"),
        time=birth_info.get("time"),
        lat=round(float(birth_info.get("lat", 0)), 4),
        lon=round(float(birth_info.get("lon", 0)), 4),
        tz_offset=birth_info.get("tz_offset"),
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def make_chart_id(birth_info: dict) -> str:
    """Deterministic: the same birth data always produces the same chart_id."""
    return "chart_" + _fingerprint(birth_info)


def compute_dasha_tree(birth_dt: datetime, moon_longitude: float) -> list[dict]:
    """Mahadasha -> Antardasha tree, day-precision, 9 x 9 = 81 periods.
    Reimplements the same first-principles Vimshottari math as
    chart.calculator.calc_vimshottari (elapsed-nakshatra-fraction method)
    but keeps day-level precision throughout instead of collapsing to
    month strings, so Antardasha periods (which can be a few months) and
    the Pratyantardasha periods derived from them (which can be days) are
    accurate. calc_vimshottari itself is untouched.
    """
    nak_idx = int(moon_longitude * 27 / 360) % 27
    nak_lord = NAKSHATRA_LORDS[nak_idx]
    nak_size_deg = 360.0 / 27
    nak_start = nak_idx * nak_size_deg
    elapsed_frac = (moon_longitude - nak_start) / nak_size_deg
    elapsed_frac = max(0.0, min(1.0, elapsed_frac))
    seq_idx = VIMSHOTTARI_SEQUENCE.index(nak_lord)

    first_md_years = VIMSHOTTARI_YEARS[nak_lord]
    elapsed_days = first_md_years * elapsed_frac * 365.25
    md_cursor = birth_dt - timedelta(days=elapsed_days)

    tree = []
    for i in range(9):
        md_lord = VIMSHOTTARI_SEQUENCE[(seq_idx + i) % 9]
        md_years = VIMSHOTTARI_YEARS[md_lord]
        md_days = md_years * 365.25
        md_start = md_cursor
        md_end = md_cursor + timedelta(days=md_days)

        antardashas = []
        ad_cursor = md_start
        ad_seq_idx = VIMSHOTTARI_SEQUENCE.index(md_lord)
        for j in range(9):
            ad_lord = VIMSHOTTARI_SEQUENCE[(ad_seq_idx + j) % 9]
            ad_years = md_years * VIMSHOTTARI_YEARS[ad_lord] / 120.0
            ad_days = ad_years * 365.25
            ad_start = ad_cursor
            ad_end = ad_cursor + timedelta(days=ad_days)
            antardashas.append({
                "lord": ad_lord,
                "start": ad_start.date().isoformat(),
                "end": ad_end.date().isoformat(),
                "years": round(ad_years, 4),
            })
            ad_cursor = ad_end

        tree.append({
            "lord": md_lord,
            "years": md_years,
            "start": md_start.date().isoformat(),
            "end": md_end.date().isoformat(),
            "antardashas": antardashas,
        })
        md_cursor = md_end

    return tree


def _pratyantardashas_for(ad_lord: str, ad_start_iso: str, ad_years: float) -> list[dict]:
    """Computed on demand (not stored in the tree) to keep the bundle a
    reasonable size - 81 MD/AD entries stored, 9 PD entries computed only
    for whichever Antardasha is currently active."""
    ad_start = datetime.fromisoformat(ad_start_iso)
    pd_seq_idx = VIMSHOTTARI_SEQUENCE.index(ad_lord)
    pd_cursor = ad_start
    out = []
    for k in range(9):
        pd_lord = VIMSHOTTARI_SEQUENCE[(pd_seq_idx + k) % 9]
        pd_years = ad_years * VIMSHOTTARI_YEARS[pd_lord] / 120.0
        pd_days = pd_years * 365.25
        pd_start = pd_cursor
        pd_end = pd_cursor + timedelta(days=pd_days)
        out.append({
            "lord": pd_lord,
            "start": pd_start.date().isoformat(),
            "end": pd_end.date().isoformat(),
        })
        pd_cursor = pd_end
    return out


def current_dasha_period(tree: list[dict], as_of: Optional[datetime] = None) -> dict:
    """Walks the MD/AD tree and returns current Mahadasha, Antardasha and
    (computed on demand) Pratyantardasha as of a given date (default: now)."""
    as_of = as_of or datetime.now()
    as_of_date = as_of.date().isoformat()
    for md in tree:
        if md["start"] <= as_of_date <= md["end"]:
            current_ad = None
            current_pd = None
            for ad in md["antardashas"]:
                if ad["start"] <= as_of_date <= ad["end"]:
                    current_ad = ad
                    for pd in _pratyantardashas_for(ad["lord"], ad["start"], ad["years"]):
                        if pd["start"] <= as_of_date <= pd["end"]:
                            current_pd = pd
                            break
                    break
            return {
                "mahadasha": {"lord": md["lord"], "start": md["start"], "end": md["end"]},
                "antardasha": current_ad,
                "pratyantardasha": current_pd,
            }
    return {"mahadasha": None, "antardasha": None, "pratyantardasha": None}


def _planet_bundle(p) -> dict:
    return {
        "sign": p.sign,
        "sign_index": p.sign_index,
        "degrees": round(p.degrees, 4),
        "minutes": round(p.minutes, 4),
        "longitude": round(p.longitude, 6),
        "house": p.house,
        "nakshatra": p.nakshatra,
        "nakshatra_lord": p.nakshatra_lord,
        "pada": p.pada,
        "retrograde": p.retrograde,
        "dignity": p.dignity,
        "sign_lord": SIGN_LORDS[p.sign_index] if 0 <= p.sign_index < 12 else None,
    }


def _chart_bundle_dict(chart) -> dict:
    house_lords = [SIGN_LORDS[(chart.ascendant_sign_index + i) % 12] for i in range(12)]
    return {
        "label": chart.label,
        "ascendant": {
            "sign": chart.ascendant_sign,
            "sign_index": chart.ascendant_sign_index,
            "degrees": round(chart.ascendant_degrees, 4),
            "longitude": round(chart.ascendant_longitude, 6),
        },
        "planets": {name: _planet_bundle(p) for name, p in chart.planets.items()},
        "houses": chart.houses,
        "house_lords": house_lords,
    }


def build_chart_bundle(birth_info: dict, birth_dt: datetime, d1, divs: dict,
                        dashas: list, strength: dict,
                        profile_name: Optional[str] = None) -> dict:
    """Assemble the canonical Chart Bundle from ALREADY-COMPUTED chart
    objects (the same d1/divs/dashas/strength the /api/chart route
    computes). Does not recompute astronomical data."""
    chart_id = make_chart_id(birth_info)
    moon_lon = d1.planets.get("Moon").longitude if "Moon" in d1.planets else 0.0
    dasha_tree = compute_dasha_tree(birth_dt, moon_lon)
    current = current_dasha_period(dasha_tree)

    divisional_bundle = {"D1": _chart_bundle_dict(d1)}
    for key, chart in divs.items():
        if key.upper() in CORE_DIVISIONS:
            divisional_bundle[key.upper()] = _chart_bundle_dict(chart)

    return {
        "chart_id": chart_id,
        "schema_version": SCHEMA_VERSION,
        "profile_name": profile_name or birth_info.get("place", "Unnamed"),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "birth_data": {
            "date": birth_info.get("date"),
            "time": birth_info.get("time"),
            "place": birth_info.get("place"),
            "lat": float(birth_info.get("lat", 0)),
            "lon": float(birth_info.get("lon", 0)),
            "tz_offset": float(birth_info.get("tz_offset", 0)),
            "utc": birth_dt.strftime("%Y-%m-%d %H:%M UTC"),
            "birth_time_confidence": birth_info.get("birth_time_confidence", "exact"),
        },
        "calculation_config": {
            "zodiac": "sidereal",
            "ayanamsa": "Lahiri (Chitrapaksha)",
            "house_system": "Whole Sign",
            "node_type": "mean",
            "ephemeris": "Swiss Ephemeris (pyswisseph)",
        },
        "divisional_charts": divisional_bundle,
        "timing": {
            "current_mahadasha": current["mahadasha"],
            "current_antardasha": current["antardasha"],
            "current_pratyantardasha": current["pratyantardasha"],
            "mahadasha_antardasha_sequence": dasha_tree,
        },
        "derived": {
            "vargottama": strength.get("vargottama", {}),
            "vimshopaka_bala": strength.get("vimshopaka_bala", {}),
        },
    }
