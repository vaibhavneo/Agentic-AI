"""
Divisional Chart (Varga) Calculator
=====================================
Implements the full Shodasavarga (16-varga) system per classical Parasara rules:
D-1, D-2, D-3, D-4, D-7, D-9, D-10, D-12, D-16, D-20, D-24, D-27, D-30, D-40, D-45, D-60.

Divisional chart formula (general):
  new_position = (start_sign + step * part) mod 12
  where part = floor(deg_in_sign / (30/N)), and start_sign / step are varga-specific.

Verification: every formula below (D-2 through D-60) was empirically checked against
TWO independent real charts computed by AstroSage (a widely-used Vedic astrology
platform) — Vaibhav's own chart (7 Jan 1981, Allahabad) and a second chart (21 Jun
1986, Chandigarh) — comparing Lagna + 9 planets per varga (20 data points per
formula total). All 15 non-D1 vargas matched 10/10 on both charts, including edge
cases (air-element signs for D-9/D-27, all five D-30 lordship zones). Source PDFs:
~/Desktop/Astrology Books/VedicReport*.pdf. This is stronger evidence than reading
a printed table by hand, since it validates actual computed behavior across many
sign/degree combinations rather than a single transcribed value.

D-60 note: classical texts (e.g. Goel, "Comprehensive Prediction by Divisional
Charts") describe two methods — a named-deity "Parashar Method" and a simpler
"Cyclical/Mathematical" method. The formula below is the Cyclical method, which is
what AstroSage (and most modern software) evidently implements in practice, and is
what the empirical verification above confirms.
"""
from __future__ import annotations

from .calculator import (
    Chart, PlanetPosition, VedicChartCalculator,
    SIGNS, PLANET_ABBR, EXALTATION, DEBILITATION, OWN_SIGNS,
    NAKSHATRA_LORDS, NAKSHATRAS,
)


def _get_dignity(planet: str, sign_idx: int) -> str:
    if EXALTATION.get(planet) == sign_idx:
        return "exalted"
    if DEBILITATION.get(planet) == sign_idx:
        return "debilitated"
    if sign_idx in OWN_SIGNS.get(planet, []):
        return "own sign"
    return "neutral"


def _make_planet(name: str, lon: float, asc_sign_idx: int,
                 retrograde: bool = False) -> PlanetPosition:
    sign_idx = int(lon / 30) % 12
    deg = lon % 30
    nak_idx  = int(lon * 27 / 360) % 27
    pada     = int((lon % (360 / 27)) / (360 / 108)) + 1
    house    = ((sign_idx - asc_sign_idx) % 12) + 1
    return PlanetPosition(
        name=name,
        longitude=lon % 360,
        sign_index=sign_idx,
        sign=SIGNS[sign_idx],
        degrees=int(deg),
        minutes=int((deg % 1) * 60),
        nakshatra=NAKSHATRAS[nak_idx],
        nakshatra_lord=NAKSHATRA_LORDS[nak_idx],
        pada=pada,
        retrograde=retrograde,
        dignity=_get_dignity(name, sign_idx),
        house=house,
    )


# ════════════════════════════════════════════════════════════════════════════
# D-2  (Hora) — Wealth, financial potential
# Rule: Odd signs → Sun/Moon halves; Even signs → Moon/Sun halves
#   First half (0–15°): odd sign → Sun hora (Leo, sign 4), even → Moon hora (Cancer, sign 3)
#   Second half (15–30°): odd → Moon hora, even → Sun hora
# ════════════════════════════════════════════════════════════════════════════

def calc_d2(planet_lon: float) -> float:
    """Return D-2 longitude (in Leo=Sun or Cancer=Moon hora)."""
    sign_idx = int(planet_lon / 30) % 12
    deg = planet_lon % 30
    odd_sign = (sign_idx % 2 == 0)  # Aries=0 is odd in Vedic (1st sign)
    first_half = deg < 15
    if odd_sign:
        hora_sign = 4 if first_half else 3   # Leo : Cancer
    else:
        hora_sign = 3 if first_half else 4   # Cancer : Leo
    return hora_sign * 30 + deg * 2 % 30


# ════════════════════════════════════════════════════════════════════════════
# D-3  (Drekkana) — Siblings, courage, initiative
# Rule per Parasara: divide each sign into 3 drekkanas of 10° each
#   1st drekkana (0–10°)   → same sign
#   2nd drekkana (10–20°)  → 5th sign from it
#   3rd drekkana (20–30°)  → 9th sign from it
# ════════════════════════════════════════════════════════════════════════════

def calc_d3(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    drek      = int(deg / 10)           # 0, 1, or 2
    offsets   = [0, 4, 8]               # same, 5th, 9th
    new_sign  = (sign_idx + offsets[drek]) % 12
    new_deg   = (deg % 10) * 3
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-7  (Saptamsa) — Children, creativity, fertility
# Rule: Each sign divided into 7 parts of 4°17' each
#   Odd signs start from same sign; Even signs start from 7th sign
# ════════════════════════════════════════════════════════════════════════════

def calc_d7(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 30.0 / 7
    part      = int(deg / part_size)    # 0–6
    odd_sign  = (sign_idx % 2 == 0)    # Vedic: Aries(0) is odd
    start     = sign_idx if odd_sign else (sign_idx + 6) % 12
    new_sign  = (start + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-9  (Navamsa) — Marriage, spouse, dharma, soul purpose (most important varga)
# Rule: Each sign divided into 9 navamsas of 3°20' each
#   Fire signs start from Aries; Earth from Capricorn; Air from Libra; Water from Cancer
# ════════════════════════════════════════════════════════════════════════════

NAVAMSA_START = {
    "fire":  0,   # Aries
    "earth": 9,   # Capricorn
    "air":   6,   # Libra
    "water": 3,   # Cancer
}
SIGN_ELEMENT = {
    0: "fire", 1: "earth", 2: "air",  3: "water",
    4: "fire", 5: "earth", 6: "air",  7: "water",
    8: "fire", 9: "earth", 10: "air", 11: "water",
}

def calc_d9(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    nav_size  = 30.0 / 9              # 3°20'
    nav_num   = int(deg / nav_size)   # 0–8
    element   = SIGN_ELEMENT[sign_idx]
    start     = NAVAMSA_START[element]
    new_sign  = (start + nav_num) % 12
    new_deg   = (deg % nav_size) / nav_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-10  (Dasamsa) — Career, profession, status, public life
# Rule: Each sign divided into 10 parts of 3° each
#   Odd signs: start from same sign; Even signs: start from 9th sign
# ════════════════════════════════════════════════════════════════════════════

def calc_d10(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 3.0
    part      = int(deg / part_size)   # 0–9
    odd_sign  = (sign_idx % 2 == 0)
    start     = sign_idx if odd_sign else (sign_idx + 8) % 12
    new_sign  = (start + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-4  (Chaturthamsa) — Fortune, property, general luck
# Rule: Each sign divided into 4 parts of 7°30' each. No odd/even split —
#   always starts from the same sign, jumping 3 signs (a Kendra/quadrant step)
#   per part: offsets [0, 3, 6, 9].
# ════════════════════════════════════════════════════════════════════════════

def calc_d4(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 7.5
    part      = int(deg / part_size)   # 0–3
    new_sign  = (sign_idx + 3 * part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-12  (Dwadasamsa) — Parents, ancestry
# Rule: Each sign divided into 12 parts of 2°30' each. No odd/even split —
#   always starts from the same sign, one sign forward per part.
# ════════════════════════════════════════════════════════════════════════════

def calc_d12(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 2.5
    part      = int(deg / part_size)   # 0–11
    new_sign  = (sign_idx + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-16  (Shodasamsa) — Vehicles, general comforts/happiness
# NOTE: "D-16" the chart is one member of the "Shodasavarga" (16-varga) *system*
#   — same numeral, different concept, worth not confusing the two.
# Rule: Each sign divided into 16 parts of 1°52'30" each. Grouped by triplicity
#   (movable/fixed/dual, i.e. sign_idx % 3): movable→Aries, fixed→Leo, dual→Sagittarius.
# ════════════════════════════════════════════════════════════════════════════

D16_TRINE_START = {0: 0, 1: 4, 2: 8}   # movable→Aries, fixed→Leo, dual→Sagittarius

def calc_d16(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 30.0 / 16
    part      = min(int(deg / part_size), 15)
    start     = D16_TRINE_START[sign_idx % 3]
    new_sign  = (start + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-20  (Vimsamsa) — Spirituality, worship, religious inclination
# Rule: Each sign divided into 20 parts of 1°30' each. Grouped by triplicity:
#   movable→Aries, fixed→Sagittarius, dual→Leo (a different trine assignment
#   order than D-16, though also fire-trine-anchored).
# ════════════════════════════════════════════════════════════════════════════

D20_TRINE_START = {0: 0, 1: 8, 2: 4}   # movable→Aries, fixed→Sagittarius, dual→Leo

def calc_d20(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 30.0 / 20
    part      = min(int(deg / part_size), 19)
    start     = D20_TRINE_START[sign_idx % 3]
    new_sign  = (start + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-24  (Chaturvimsamsa / Siddhamsa) — Education, learning, knowledge
# Rule: Each sign divided into 24 parts of 1°15' each.
#   Odd signs start from Leo; even signs start from Cancer.
# ════════════════════════════════════════════════════════════════════════════

def calc_d24(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 30.0 / 24
    part      = min(int(deg / part_size), 23)
    odd_sign  = (sign_idx % 2 == 0)
    start     = 4 if odd_sign else 3   # Leo : Cancer
    new_sign  = (start + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-27  (Saptavimsamsa / Bhamsa) — Strengths and weaknesses
# Rule: Each sign divided into 27 parts of 1°6'40" each. Element-anchored like
#   D-9, but with a different element→sign assignment: fire→Aries, earth→Cancer,
#   water→Capricorn, air→Libra (earth/water swapped relative to D-9's mapping).
#   NOTE: the air-group start was directly confirmed by empirical cross-check
#   (a second reference chart had air-sign planets); fire/earth/water were also
#   directly confirmed on the first reference chart.
# ════════════════════════════════════════════════════════════════════════════

D27_ELEMENT_START = {"fire": 0, "earth": 3, "air": 6, "water": 9}

def calc_d27(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 30.0 / 27
    part      = min(int(deg / part_size), 26)
    element   = SIGN_ELEMENT[sign_idx]
    start     = D27_ELEMENT_START[element]
    new_sign  = (start + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-30  (Trimsamsa) — Misfortunes, difficulties, character weaknesses
# Structurally different from every other varga: UNEQUAL degree spans, assigned
# by planetary lordship rather than a uniform N-way division.
#   Odd signs (0-5 Mars, 5-10 Saturn, 10-18 Jupiter, 18-25 Mercury, 25-30 Venus):
#     resulting sign = that planet's own sign that is itself classified "odd".
#   Even signs (reversed order: 0-5 Venus, 5-12 Mercury, 12-20 Jupiter,
#     20-25 Saturn, 25-30 Mars): resulting sign = that planet's own "even" sign.
# ════════════════════════════════════════════════════════════════════════════

# (upper_degree_bound, resulting_sign_index) — own-odd-sign for the ruling planet
D30_ODD_ZONES  = [(5, 0), (10, 10), (18, 8), (25, 2), (30, 6)]   # Ar,Aq,Sg,Ge,Li
# own-even-sign for the ruling planet, reversed order
D30_EVEN_ZONES = [(5, 1), (12, 5), (20, 11), (25, 9), (30, 7)]   # Ta,Vi,Pi,Cp,Sc

def calc_d30(planet_lon: float) -> float:
    sign_idx = int(planet_lon / 30) % 12
    deg      = planet_lon % 30
    odd_sign = (sign_idx % 2 == 0)
    zones    = D30_ODD_ZONES if odd_sign else D30_EVEN_ZONES
    for upper, new_sign in zones:
        if deg < upper:
            return new_sign * 30
    return zones[-1][1] * 30


# ════════════════════════════════════════════════════════════════════════════
# D-40  (Khavedamsa) — Auspicious/inauspicious general effects
# Rule: Each sign divided into 40 parts of 45' each.
#   Odd signs start from Aries; even signs start from Libra.
# ════════════════════════════════════════════════════════════════════════════

def calc_d40(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 30.0 / 40
    part      = min(int(deg / part_size), 39)
    odd_sign  = (sign_idx % 2 == 0)
    start     = 0 if odd_sign else 6   # Aries : Libra
    new_sign  = (start + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-45  (Akshavedamsa) — General character, conduct
# Rule: Each sign divided into 45 parts of 40' each. Grouped by triplicity,
#   same assignment as D-16: movable→Aries, fixed→Leo, dual→Sagittarius.
# ════════════════════════════════════════════════════════════════════════════

def calc_d45(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 30.0 / 45
    part      = min(int(deg / part_size), 44)
    start     = D16_TRINE_START[sign_idx % 3]   # same trine pattern as D-16
    new_sign  = (start + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# D-60  (Shashtiamsa) — Overall past-life karma, general life results.
# Classically considered to carry more weight than the birth chart itself.
# Rule (Cyclical/Mathematical method — see module docstring): each sign divided
#   into 60 parts of 30' each. No odd/even split — always starts from the same
#   sign, one sign forward per part.
# ════════════════════════════════════════════════════════════════════════════

def calc_d60(planet_lon: float) -> float:
    sign_idx  = int(planet_lon / 30) % 12
    deg       = planet_lon % 30
    part_size = 30.0 / 60
    part      = min(int(deg / part_size), 59)
    new_sign  = (sign_idx + part) % 12
    new_deg   = (deg % part_size) / part_size * 30
    return new_sign * 30 + new_deg


# ════════════════════════════════════════════════════════════════════════════
# Master function: compute all divisional charts from D-1
# ════════════════════════════════════════════════════════════════════════════

def build_divisional_charts(d1: Chart) -> dict[str, Chart]:
    """
    Compute the full Shodasavarga (16-varga) set from the D-1 chart.
    Returns dict keyed by "D2", "D3", "D4", "D7", "D9", "D10", "D12", "D16",
    "D20", "D24", "D27", "D30", "D40", "D45", "D60".
    """
    divs: dict[str, Chart] = {}

    div_funcs = {
        "D2":  ("D-2 (Hora — Wealth)", calc_d2),
        "D3":  ("D-3 (Drekkana — Siblings/Courage)", calc_d3),
        "D4":  ("D-4 (Chaturthamsa — Fortune/Property)", calc_d4),
        "D7":  ("D-7 (Saptamsa — Children)", calc_d7),
        "D9":  ("D-9 (Navamsa — Soul/Spouse/Dharma)", calc_d9),
        "D10": ("D-10 (Dasamsa — Career/Status)", calc_d10),
        "D12": ("D-12 (Dwadasamsa — Parents)", calc_d12),
        "D16": ("D-16 (Shodasamsa — Vehicles/Comforts)", calc_d16),
        "D20": ("D-20 (Vimsamsa — Spirituality/Worship)", calc_d20),
        "D24": ("D-24 (Chaturvimsamsa — Education/Learning)", calc_d24),
        "D27": ("D-27 (Saptavimsamsa — Strengths/Weaknesses)", calc_d27),
        "D30": ("D-30 (Trimsamsa — Misfortunes/Character)", calc_d30),
        "D40": ("D-40 (Khavedamsa — Auspicious/Inauspicious Effects)", calc_d40),
        "D45": ("D-45 (Akshavedamsa — Character/Conduct)", calc_d45),
        "D60": ("D-60 (Shashtiamsa — Overall Life Results)", calc_d60),
    }

    for key, (label, fn) in div_funcs.items():
        planets: dict[str, PlanetPosition] = {}

        # Transform each planet
        for name, p in d1.planets.items():
            new_lon = fn(p.longitude)
            planets[name] = _make_planet(name, new_lon, 0, p.retrograde)

        # Transform Ascendant
        asc_lon = fn(d1.ascendant_longitude)
        asc_sign_idx = int(asc_lon / 30) % 12

        # Recompute house placements relative to this chart's ascendant
        for name, p in planets.items():
            p.house = ((p.sign_index - asc_sign_idx) % 12) + 1

        divs[key] = Chart(
            label=label,
            ascendant_longitude=asc_lon,
            ascendant_sign=SIGNS[asc_sign_idx],
            ascendant_sign_index=asc_sign_idx,
            ascendant_degrees=asc_lon % 30,
            planets=planets,
            houses=[(asc_sign_idx + i) % 12 for i in range(12)],
        )

    return divs
