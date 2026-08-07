"""
Vedic Astrology Chart Calculator
==================================
Uses Swiss Ephemeris (pyswisseph) with Lahiri Ayanamsa (Chitrapaksha).
Calculates sidereal planet positions, Ascendant, all 12 houses.
Reference: Narasimha Rao — Vedic Astrology: An Integrated Approach
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import swisseph as swe

# ── Constants ──────────────────────────────────────────────────────────────

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]
SIGN_ABBR = ["Ar", "Ta", "Ge", "Ca", "Le", "Vi", "Li", "Sc", "Sg", "Cp", "Aq", "Pi"]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishtha",
    "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]
NAKSHATRA_LORDS = [
    "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu",
    "Jupiter", "Saturn", "Mercury", "Ketu", "Venus", "Sun",
    "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury",
    "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu",
    "Jupiter", "Saturn", "Mercury",
]

# Swiss Ephemeris planet IDs
PLANETS = {
    "Sun":     swe.SUN,
    "Moon":    swe.MOON,
    "Mars":    swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus":   swe.VENUS,
    "Saturn":  swe.SATURN,
    "Rahu":    swe.MEAN_NODE,   # North Node
}

PLANET_ABBR = {
    "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me",
    "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa",
    "Rahu": "Ra", "Ketu": "Ke",
}

# Natural benefics / malefics
BENEFICS  = {"Jupiter", "Venus", "Moon", "Mercury"}
MALEFICS  = {"Sun", "Mars", "Saturn", "Rahu", "Ketu"}

# Planetary exaltation signs (0-based sign index)
EXALTATION = {
    "Sun": 0,      # Aries
    "Moon": 1,     # Taurus
    "Mars": 9,     # Capricorn
    "Mercury": 5,  # Virgo
    "Jupiter": 3,  # Cancer
    "Venus": 11,   # Pisces
    "Saturn": 6,   # Libra
    "Rahu": 1,     # Taurus (widely accepted)
    "Ketu": 7,     # Scorpio
}
DEBILITATION = {p: (s + 6) % 12 for p, s in EXALTATION.items()}

# Own signs
OWN_SIGNS = {
    "Sun":     [4],        # Leo
    "Moon":    [3],        # Cancer
    "Mars":    [0, 7],     # Aries, Scorpio
    "Mercury": [2, 5],     # Gemini, Virgo
    "Jupiter": [8, 11],    # Sagittarius, Pisces
    "Venus":   [1, 6],     # Taurus, Libra
    "Saturn":  [9, 10],    # Capricorn, Aquarius
    "Rahu":    [],
    "Ketu":    [],
}

# Sign rulers
SIGN_LORDS = ["Mars","Venus","Mercury","Moon","Sun","Mercury",
               "Venus","Mars","Jupiter","Saturn","Saturn","Jupiter"]

# Vimshottari Dasha years
VIMSHOTTARI_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}
VIMSHOTTARI_SEQUENCE = ["Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury"]


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class PlanetPosition:
    name: str
    longitude: float          # absolute sidereal longitude (0–360)
    sign_index: int           # 0=Aries … 11=Pisces
    sign: str
    degrees: float            # degrees within sign (0–30)
    minutes: float
    nakshatra: str
    nakshatra_lord: str
    pada: int                 # 1–4
    retrograde: bool = False
    dignity: str = "neutral"  # exalted/own/debilitated/neutral
    house: int = 0            # house placement in D-1 (set later)

    def short(self) -> str:
        r = "R" if self.retrograde else ""
        return f"{PLANET_ABBR.get(self.name, self.name[:2])}{r} {self.sign[:2]}{self.degrees:.0f}°{self.minutes:.0f}'"

    def nakshatra_pada(self) -> str:
        return f"{self.nakshatra} Pada {self.pada} (lord: {self.nakshatra_lord})"


@dataclass
class Chart:
    label: str                          # "D-1 (Rasi)", "D-9 (Navamsa)", etc.
    ascendant_longitude: float
    ascendant_sign: str
    ascendant_sign_index: int
    ascendant_degrees: float
    planets: dict[str, PlanetPosition] = field(default_factory=dict)
    houses: list[int] = field(default_factory=list)  # sign index for houses 1-12


# ── Core Calculator ────────────────────────────────────────────────────────

class VedicChartCalculator:
    """
    Computes sidereal Vedic charts using Swiss Ephemeris.
    House system: Whole Sign (most common in Vedic astrology)
    Ayanamsa: Lahiri (Chitrapaksha) — the standard for India
    """

    def __init__(self):
        swe.set_sid_mode(swe.SIDM_LAHIRI)

    # ── Julian Day conversion ────────────────────────────────────────────

    @staticmethod
    def to_julian_day(dt: datetime) -> float:
        """Convert datetime (UTC) to Julian Day Number."""
        return swe.julday(dt.year, dt.month, dt.day,
                          dt.hour + dt.minute / 60.0 + dt.second / 3600.0)

    # ── Nakshatra from longitude ─────────────────────────────────────────

    @staticmethod
    def nakshatra_from_longitude(lon: float) -> tuple[str, str, int]:
        """Returns (nakshatra_name, nakshatra_lord, pada)."""
        nak_idx  = int(lon * 27 / 360) % 27
        pada     = int((lon % (360 / 27)) / (360 / 108)) + 1
        return NAKSHATRAS[nak_idx], NAKSHATRA_LORDS[nak_idx], pada

    # ── Planet dignity ───────────────────────────────────────────────────

    @staticmethod
    def get_dignity(planet: str, sign_idx: int) -> str:
        if EXALTATION.get(planet) == sign_idx:
            return "exalted"
        if DEBILITATION.get(planet) == sign_idx:
            return "debilitated"
        if sign_idx in OWN_SIGNS.get(planet, []):
            return "own sign"
        return "neutral"

    # ── Calculate one planet position ────────────────────────────────────

    def calc_planet(self, jd: float, name: str, swe_id: int) -> PlanetPosition:
        flags = swe.FLG_SIDEREAL | swe.FLG_SPEED
        result, _ = swe.calc_ut(jd, swe_id, flags)
        lon       = result[0] % 360
        speed     = result[3]
        retro     = speed < 0

        sign_idx  = int(lon / 30)
        deg_in_sign = lon % 30
        degrees   = int(deg_in_sign)
        minutes   = int((deg_in_sign - degrees) * 60)

        nak, nak_lord, pada = self.nakshatra_from_longitude(lon)
        dignity = self.get_dignity(name, sign_idx)

        return PlanetPosition(
            name=name,
            longitude=lon,
            sign_index=sign_idx,
            sign=SIGNS[sign_idx],
            degrees=degrees,
            minutes=minutes,
            nakshatra=nak,
            nakshatra_lord=nak_lord,
            pada=pada,
            retrograde=retro,
            dignity=dignity,
        )

    # ── Calculate Ascendant ──────────────────────────────────────────────

    def calc_ascendant(self, jd: float, lat: float, lon: float) -> tuple[float, int, float]:
        """Returns (asc_longitude, sign_index, degrees_in_sign)."""
        ayanamsa = swe.get_ayanamsa_ut(jd)
        cusps, ascmc = swe.houses(jd, lat, lon, b'W')  # W = Whole Sign
        asc_tropical = ascmc[0]
        asc_sid = (asc_tropical - ayanamsa) % 360
        sign_idx = int(asc_sid / 30)
        deg = asc_sid % 30
        return asc_sid, sign_idx, deg

    # ── Build full D-1 chart ─────────────────────────────────────────────

    def build_d1(self, jd: float, lat: float, lon: float) -> Chart:
        asc_lon, asc_sign_idx, asc_deg = self.calc_ascendant(jd, lat, lon)

        # Whole Sign houses: house 1 = Asc sign, house 2 = next sign, etc.
        houses = [(asc_sign_idx + i) % 12 for i in range(12)]

        planets: dict[str, PlanetPosition] = {}

        # Calculate all planets
        for name, swe_id in PLANETS.items():
            p = self.calc_planet(jd, name, swe_id)
            # House placement (Whole Sign)
            p.house = ((p.sign_index - asc_sign_idx) % 12) + 1
            planets[name] = p

        # Ketu = Rahu + 180°
        rahu = planets["Rahu"]
        ketu_lon = (rahu.longitude + 180) % 360
        ketu_sign_idx = int(ketu_lon / 30)
        ketu_deg = ketu_lon % 30
        ketu_nak, ketu_lord, ketu_pada = self.nakshatra_from_longitude(ketu_lon)
        planets["Ketu"] = PlanetPosition(
            name="Ketu",
            longitude=ketu_lon,
            sign_index=ketu_sign_idx,
            sign=SIGNS[ketu_sign_idx],
            degrees=int(ketu_deg),
            minutes=int((ketu_deg % 1) * 60),
            nakshatra=ketu_nak,
            nakshatra_lord=ketu_lord,
            pada=ketu_pada,
            retrograde=True,
            dignity=self.get_dignity("Ketu", ketu_sign_idx),
            house=((ketu_sign_idx - asc_sign_idx) % 12) + 1,
        )

        return Chart(
            label="D-1 (Rasi — Natal)",
            ascendant_longitude=asc_lon,
            ascendant_sign=SIGNS[asc_sign_idx],
            ascendant_sign_index=asc_sign_idx,
            ascendant_degrees=asc_deg,
            planets=planets,
            houses=houses,
        )

    # ── Vimshottari Dasha ────────────────────────────────────────────────

    def calc_vimshottari(self, jd: float, moon_longitude: float) -> list[dict]:
        """Calculate current and upcoming Vimshottari Dasha periods."""
        nak_idx  = int(moon_longitude * 27 / 360) % 27
        nak_lord = NAKSHATRA_LORDS[nak_idx]

        # Progress through nakshatra (fraction elapsed)
        nak_size_deg = 360 / 27
        nak_start    = nak_idx * nak_size_deg
        elapsed_frac = (moon_longitude - nak_start) / nak_size_deg
        elapsed_frac = max(0.0, min(1.0, elapsed_frac))

        # Find starting dasha
        seq_idx = VIMSHOTTARI_SEQUENCE.index(nak_lord)
        start_dasha_lord = nak_lord
        start_years_elapsed = VIMSHOTTARI_YEARS[start_dasha_lord] * elapsed_frac

        # Build dasha timeline (birth to ~120 years)
        from datetime import timedelta
        birth_dt = swe.revjul(jd)
        birth_year = birth_dt[0] + birth_dt[1]/12 + birth_dt[2]/365.25

        dashas = []
        current_year = birth_year - start_years_elapsed
        idx = seq_idx

        for _ in range(9):  # one full cycle
            lord = VIMSHOTTARI_SEQUENCE[idx % 9]
            years = VIMSHOTTARI_YEARS[lord]
            start_year = current_year
            end_year   = current_year + years

            # Convert to readable year/month
            start_yr = int(start_year)
            start_mo = int((start_year - start_yr) * 12) + 1
            end_yr   = int(end_year)
            end_mo   = int((end_year - end_yr) * 12) + 1

            dashas.append({
                "lord": lord,
                "years": years,
                "start": f"{start_yr}-{start_mo:02d}",
                "end":   f"{end_yr}-{end_mo:02d}",
            })
            current_year = end_year
            idx += 1

        return dashas

    def calc_dasha_bhukti(self, jd: float, moon_longitude: float) -> list:
        """Vimshottari Mahadasha timeline WITH nested Antardashas (bhuktis).

        Returns a list of dicts, each an MD:
            {lord, start, end, bhuktis: [{lord, start, end}, ...]}
        where start/end are fractional decimal years (e.g. 2027.29). Bhukti
        durations follow the classical rule AD = MD_years * AD_lord_years / 120,
        in Vimshottari sequence starting from the MD lord. This is the grounded
        substitute for letting the LLM guess sub-period dates."""
        nak_idx  = int(moon_longitude * 27 / 360) % 27
        nak_lord = NAKSHATRA_LORDS[nak_idx]
        nak_size_deg = 360 / 27
        nak_start    = nak_idx * nak_size_deg
        elapsed_frac = max(0.0, min(1.0, (moon_longitude - nak_start) / nak_size_deg))

        seq_idx = VIMSHOTTARI_SEQUENCE.index(nak_lord)
        start_years_elapsed = VIMSHOTTARI_YEARS[nak_lord] * elapsed_frac

        birth_dt   = swe.revjul(jd)
        birth_year = birth_dt[0] + birth_dt[1] / 12 + birth_dt[2] / 365.25

        out = []
        md_start = birth_year - start_years_elapsed
        for i in range(9):
            md_lord  = VIMSHOTTARI_SEQUENCE[(seq_idx + i) % 9]
            md_years = VIMSHOTTARI_YEARS[md_lord]
            md_end   = md_start + md_years

            bhuktis = []
            ad_start = md_start
            ad_seq_idx = VIMSHOTTARI_SEQUENCE.index(md_lord)
            for j in range(9):
                ad_lord  = VIMSHOTTARI_SEQUENCE[(ad_seq_idx + j) % 9]
                ad_years = md_years * VIMSHOTTARI_YEARS[ad_lord] / 120.0
                bhuktis.append({"lord": ad_lord,
                                "start": round(ad_start, 3),
                                "end":   round(ad_start + ad_years, 3)})
                ad_start += ad_years

            out.append({"lord": md_lord,
                        "start": round(md_start, 3),
                        "end":   round(md_end, 3),
                        "bhuktis": bhuktis})
            md_start = md_end
        return out
