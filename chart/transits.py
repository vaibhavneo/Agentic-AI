"""Gochara (transit) computation — where the planets are NOW, or on any target
date the user asks about, relative to the natal chart.

Reuses the natal calculator's Swiss Ephemeris machinery. Vedic transits are
judged from the natal Moon (Janma Rashi / Chandra Lagna) and from the natal
Lagna — both are already fixed by the birth chart, so a transit needs only a
date (no birth place, no ascendant recomputation, no timezone precision for the
slow planets that actually drive event timing).

Public API:
    compute_transit_positions(calc, when_utc)  -> dict[name -> PlanetPosition]
    build_transit_context(calc, natal_d1, when_utc, label) -> str  (LLM block)
    extract_target_times(question, now)        -> list[(label, datetime)]
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from chart.calculator import (
    PLANETS,
    SIGNS,
    VedicChartCalculator,
    Chart,
    PlanetPosition,
)

TRANSIT_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter",
                   "Venus", "Saturn", "Rahu", "Ketu"]

_ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th",
        7: "7th", 8: "8th", 9: "9th", 10: "10th", 11: "11th", 12: "12th"}

# Benefic gochara houses (counted from the natal Moon) for the slow benefic.
_JUPITER_GOOD_FROM_MOON = {2, 5, 7, 9, 11}


def _house_from(sign_idx: int, ref_sign_idx: int) -> int:
    """Whole-sign house number of `sign_idx` counted from `ref_sign_idx`."""
    return ((sign_idx - ref_sign_idx) % 12) + 1


def compute_transit_positions(calc: VedicChartCalculator,
                              when_utc: datetime) -> dict:
    """All 9 grahas at `when_utc` (UTC). House fields are left unset here —
    they are natal-relative and filled in by build_transit_context."""
    jd = calc.to_julian_day(when_utc)
    planets: dict = {}
    for name, swe_id in PLANETS.items():
        planets[name] = calc.calc_planet(jd, name, swe_id)

    # Ketu = Rahu + 180° (same construction the natal builder uses)
    rahu = planets["Rahu"]
    ketu_lon = (rahu.longitude + 180) % 360
    ketu_sign_idx = int(ketu_lon / 30)
    deg_in_sign = ketu_lon % 30
    ketu_nak, ketu_lord, ketu_pada = calc.nakshatra_from_longitude(ketu_lon)
    planets["Ketu"] = PlanetPosition(
        name="Ketu",
        longitude=ketu_lon,
        sign_index=ketu_sign_idx,
        sign=SIGNS[ketu_sign_idx],
        degrees=int(deg_in_sign),
        minutes=int((deg_in_sign - int(deg_in_sign)) * 60),
        nakshatra=ketu_nak,
        nakshatra_lord=ketu_lord,
        pada=ketu_pada,
        retrograde=True,          # nodes are always retrograde
        dignity=calc.get_dignity("Ketu", ketu_sign_idx),
    )
    return planets


def _sade_sati_note(saturn_sign: int, moon_sign: int) -> str:
    """Saturn's Sade Sati / Kantaka / Ashtama status relative to natal Moon."""
    h = _house_from(saturn_sign, moon_sign)   # Saturn's house from the Moon
    if h == 12:
        return ("⚠️ SADE SATI — Rising phase (Saturn in the 12th from natal Moon). "
                "The first ~2.5 years of the 7.5-year Sade Sati.")
    if h == 1:
        return ("⚠️ SADE SATI — Peak phase (Saturn transiting the natal Moon sign). "
                "The most intense middle ~2.5 years.")
    if h == 2:
        return ("⚠️ SADE SATI — Setting phase (Saturn in the 2nd from natal Moon). "
                "The final ~2.5 years, easing off.")
    if h == 4:
        return "⚠️ Kantaka / Ardha-ashtama Shani (Saturn in the 4th from natal Moon) — ~2.5 yrs of pressure on home/peace."
    if h == 8:
        return "⚠️ Ashtama Shani (Saturn in the 8th from natal Moon) — ~2.5 yrs of upheaval/health caution."
    return f"Not in Sade Sati (Saturn is in the {_ORD[h]} from the natal Moon)."


def build_transit_context(calc: VedicChartCalculator, natal_d1: Chart,
                          when_utc: datetime, label: str) -> str:
    """A structured, LLM-ready gochara block for one moment in time. Every
    transiting planet is placed BOTH by the natal Lagna (which bhava it lights
    up) and by the natal Moon (classical gochara), plus the load-bearing
    slow-planet events: Sade Sati, Jupiter's transit, and the Rahu/Ketu axis."""
    moon = natal_d1.planets.get("Moon")
    moon_sign = moon.sign_index if moon else natal_d1.ascendant_sign_index
    asc_sign = natal_d1.ascendant_sign_index

    tp = compute_transit_positions(calc, when_utc)

    lines = [f"### Transits — {label}",
             f"(as of {when_utc.strftime('%Y-%m-%d')} UTC; natal Moon in "
             f"{SIGNS[moon_sign]}, natal Lagna in {SIGNS[asc_sign]})",
             "",
             "Planet   Sign          Deg   Nak                House(fromLagna)  House(fromMoon)  State"]
    for name in TRANSIT_PLANETS:
        p = tp[name]
        h_lagna = _house_from(p.sign_index, asc_sign)
        h_moon = _house_from(p.sign_index, moon_sign)
        state = []
        if p.retrograde and name not in ("Rahu", "Ketu", "Sun", "Moon"):
            state.append("retrograde")
        if p.dignity in ("exalted", "debilitated", "own sign"):
            state.append(p.dignity)
        lines.append(
            f"{name:8s} {p.sign:12s} {p.degrees:2d}°   {p.nakshatra:16s}  "
            f"{_ORD[h_lagna]:>4s} house        {_ORD[h_moon]:>4s} house       "
            f"{', '.join(state) if state else '-'}"
        )

    # Notable slow-planet events — what actually drives event timing.
    sat = tp["Saturn"]
    jup = tp["Jupiter"]
    rah = tp["Rahu"]
    notes = ["", "Notable slow-planet transits (event-timing drivers):"]
    notes.append("- Saturn: " + _sade_sati_note(sat.sign_index, moon_sign)
                 + f" Saturn is transiting the native's {_ORD[_house_from(sat.sign_index, asc_sign)]} "
                   f"house (from Lagna), in {sat.sign}"
                 + (" (retrograde)." if sat.retrograde else "."))
    j_moon = _house_from(jup.sign_index, moon_sign)
    j_lagna = _house_from(jup.sign_index, asc_sign)
    j_good = "favorable" if j_moon in _JUPITER_GOOD_FROM_MOON else "mixed/challenging"
    notes.append(f"- Jupiter: in {jup.sign}, the {_ORD[j_moon]} from natal Moon "
                 f"({j_good} gochara) and the native's {_ORD[j_lagna]} house from Lagna"
                 + (" (retrograde)." if jup.retrograde else "."))
    notes.append(f"- Rahu/Ketu axis: Rahu in {rah.sign} "
                 f"(native's {_ORD[_house_from(rah.sign_index, asc_sign)]} house), "
                 f"Ketu in {tp['Ketu'].sign} "
                 f"(native's {_ORD[_house_from(tp['Ketu'].sign_index, asc_sign)]} house).")

    return "\n".join(lines + notes)


def _decimal_year_to_str(y: float) -> str:
    """2027.29 -> '2027-04'."""
    yr = int(y)
    mo = min(12, max(1, int(round((y - yr) * 12)) + 1))
    return f"{yr}-{mo:02d}"


def build_dasha_bhukti_context(calc: VedicChartCalculator, jd: float,
                               moon_longitude: float, now: datetime,
                               until_year: int) -> str:
    """Grounded Mahadasha→Antardasha (bhukti) timeline covering the currently
    operating period through `until_year`. Prevents the LLM from inventing
    sub-period dates — the single biggest hallucination risk in timing answers."""
    timeline = calc.calc_dasha_bhukti(jd, moon_longitude)
    now_dec = now.year + (now.month - 1) / 12.0
    horizon = max(until_year + 1, now.year + 1)

    lines = ["### Vimshottari Dasha → Bhukti (Antardasha) timeline — GROUNDED",
             "(Mahadasha with its sub-periods; fractional decimal years. Use these "
             "EXACT dates for timing — do not compute your own sub-periods.)", ""]
    for md in timeline:
        if md["end"] < now_dec or md["start"] > horizon:
            continue                      # only MDs overlapping now..horizon
        cur = " ← CURRENT" if md["start"] <= now_dec < md["end"] else ""
        lines.append(f"Mahadasha {md['lord']}: "
                     f"{_decimal_year_to_str(md['start'])} → "
                     f"{_decimal_year_to_str(md['end'])}{cur}")
        for b in md["bhuktis"]:
            if b["end"] < now_dec or b["start"] > horizon:
                continue
            bcur = " ← current sub-period" if b["start"] <= now_dec < b["end"] else ""
            lines.append(f"    {md['lord']}–{b['lord']:8s} "
                         f"{_decimal_year_to_str(b['start'])} → "
                         f"{_decimal_year_to_str(b['end'])}{bcur}")
    return "\n".join(lines)


# ── Target-date extraction ──────────────────────────────────────────────────

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def extract_target_times(question: str, now: datetime) -> list:
    """Best-effort parse of a future/past moment the user names in their
    question, so 'will she travel in 2027?' or 'next March' computes transits
    for THAT time. Always returns ('Right now', now) first; appends at most one
    parsed target. Never raises — an unparseable question just yields 'now'."""
    out = [("Right now (current transits)", now)]
    if not question:
        return out
    q = question.lower()

    try:
        year = None
        month = None

        m = re.search(r"\b(20\d{2})\b", q)         # explicit 4-digit year 2000-2099
        if m:
            year = int(m.group(1))

        for token, num in _MONTHS.items():          # month name
            if re.search(r"\b" + token + r"\b", q):
                month = num
                break

        if year is None:
            if "next year" in q:
                year = now.year + 1
            elif "this year" in q:
                year = now.year
            else:
                rel = re.search(r"\bin\s+(\d{1,2})\s+years?\b", q) or \
                      re.search(r"\b(\d{1,2})\s+years?\s+from\s+now\b", q)
                if rel:
                    year = now.year + int(rel.group(1))
                elif month is not None:
                    # A bare month with no year → the next occurrence of it.
                    year = now.year if month >= now.month else now.year + 1

        if year is None:
            return out

        mm = month or 7          # mid-year if only a year was given
        target = datetime(year, mm, 15, 12, 0, tzinfo=timezone.utc)
        label = target.strftime('%B %Y') if month is not None else f"the year {year}"
        # Only add if it's meaningfully different from 'now'.
        if abs((target - now.replace(tzinfo=timezone.utc)).days) > 20:
            out.append((label, target))
    except (ValueError, OverflowError):
        pass
    return out
