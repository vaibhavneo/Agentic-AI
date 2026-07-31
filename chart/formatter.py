"""
Chart Formatter — ASCII display of Vedic charts (South Indian style grid)
and structured text summaries for the AI prediction engine.
"""
from __future__ import annotations

from .calculator import Chart, SIGNS, PLANET_ABBR, SIGN_LORDS


_ORDINAL = {1:"1st",2:"2nd",3:"3rd",4:"4th",5:"5th",6:"6th",7:"7th",
            8:"8th",9:"9th",10:"10th",11:"11th",12:"12th"}


def house_lordships(chart: Chart) -> tuple[dict[int, tuple[str, str]], dict[str, list[int]]]:
    """Deterministic bhava-lord mapping for a chart, using Whole-Sign houses.

    Returns:
      by_house: {house_number: (sign_name, lord_planet)}
      by_lord:  {planet: [house_numbers it rules]}  (a planet can rule two houses)

    This removes the single biggest source of LLM error in chart analysis:
    the model guessing which planet is "the Nth lord". For a Taurus lagna it
    now KNOWS Venus rules the 1st & 6th, Mars the 7th, Jupiter the 8th & 11th,
    etc., rather than inferring it and getting it wrong.
    """
    by_house: dict[int, tuple[str, str]] = {}
    by_lord: dict[str, list[int]] = {}
    for h in range(1, 13):
        sign_idx = chart.houses[h - 1] if (h - 1) < len(chart.houses) else None
        if sign_idx is None:
            continue
        sign = SIGNS[sign_idx]
        lord = SIGN_LORDS[sign_idx]
        by_house[h] = (sign, lord)
        by_lord.setdefault(lord, []).append(h)
    return by_house, by_lord


def format_house_lords(chart: Chart) -> str:
    """Human/LLM-readable house-lordship block for a chart."""
    by_house, by_lord = house_lordships(chart)
    lines = ["House Lords (bhava lords — sign on each house cusp and its ruler):"]
    for h in range(1, 13):
        if h in by_house:
            sign, lord = by_house[h]
            lines.append(f"  {_ORDINAL[h]} house = {sign} → ruled by {lord}")
    lines.append("Planetary lordships (which house(s) each planet rules):")
    for planet in ["Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn"]:
        houses = by_lord.get(planet, [])
        if houses:
            hs = " & ".join(_ORDINAL[h] for h in houses)
            tag = " — this is the Lagnesh (1st lord)" if 1 in houses else ""
            lines.append(f"  {planet}: {hs} lord{tag}")
    return "\n".join(lines)


# ── South Indian chart grid (fixed sign positions) ────────────────────────
# South Indian layout:
#  Pi  Ar  Ta  Ge
#  Aq          Ca
#  Cp          Le
#  Sg  Sc  Li  Vi

SI_GRID = [
    [11, 0, 1, 2],
    [10, -1, -1, 3],
    [9,  -1, -1, 4],
    [8,  7,  6, 5],
]

CELL_WIDTH  = 14
CELL_HEIGHT = 3


def format_south_indian(chart: Chart) -> str:
    """Render a South Indian square chart in ASCII."""
    # Build sign → planets map
    sign_planets: dict[int, list[str]] = {i: [] for i in range(12)}
    for name, p in chart.planets.items():
        abbr = PLANET_ABBR.get(name, name[:2])
        if p.retrograde and name not in ("Rahu", "Ketu"):
            abbr += "R"
        sign_planets[p.sign_index].append(abbr)

    # Mark ascendant
    asc_sign = chart.ascendant_sign_index
    asc_deg  = chart.ascendant_degrees
    sign_planets[asc_sign].insert(0, f"Asc{asc_deg:.0f}°")

    lines = []
    separator = "+" + ("-" * CELL_WIDTH + "+") * 4

    for row in SI_GRID:
        lines.append(separator)
        # 3 content rows per cell
        for sub in range(CELL_HEIGHT):
            row_parts = []
            for col_sign in row:
                if col_sign == -1:
                    if sub == 1:
                        row_parts.append(" " * CELL_WIDTH)
                    else:
                        row_parts.append(" " * CELL_WIDTH)
                else:
                    sign_name = SIGNS[col_sign][:2].upper()
                    cell_content = []
                    if sub == 0:
                        cell_content.append(f" {sign_name}")
                    elif sub == 1:
                        planets_here = sign_planets.get(col_sign, [])
                        cell_content.append(" " + " ".join(planets_here[:3]))
                    elif sub == 2:
                        planets_here = sign_planets.get(col_sign, [])
                        if len(planets_here) > 3:
                            cell_content.append(" " + " ".join(planets_here[3:]))
                        else:
                            cell_content.append("")
                    row_parts.append((cell_content[0] if cell_content else "").ljust(CELL_WIDTH))
            lines.append("|" + "|".join(row_parts) + "|")
    lines.append(separator)

    header = f"\n  {'─'*58}\n  {chart.label.center(58)}\n  {'─'*58}"
    return header + "\n" + "\n".join(lines)


def format_planet_table(chart: Chart) -> str:
    """Tabular planet positions."""
    lines = [
        f"\n  {'─'*72}",
        f"  Planet Positions — {chart.label}",
        f"  {'─'*72}",
        f"  {'Planet':<10} {'Sign':<14} {'Deg':<8} {'House':<6} {'Dignity':<12} {'Nakshatra & Pada'}",
        f"  {'─'*72}",
    ]
    # Ascendant first
    lines.append(
        f"  {'Ascendant':<10} {chart.ascendant_sign:<14} "
        f"{chart.ascendant_degrees:.1f}°{'':>3} {'1':<6} {'':12}"
    )
    # Planets in house order
    order = ["Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn","Rahu","Ketu"]
    for name in order:
        if name not in chart.planets:
            continue
        p = chart.planets[name]
        deg_str = f"{p.degrees}°{p.minutes:02d}'"
        retro   = " (R)" if p.retrograde and name not in ("Rahu","Ketu") else ""
        lines.append(
            f"  {(name+retro):<10} {p.sign:<14} {deg_str:<8} "
            f"H{p.house:<5} {p.dignity:<12} {p.nakshatra} P{p.pada}"
        )
    lines.append(f"  {'─'*72}")
    return "\n".join(lines)


def format_full_chart_text(chart: Chart) -> str:
    """Combined ASCII grid + planet table."""
    return format_south_indian(chart) + "\n" + format_planet_table(chart)


def chart_to_analysis_context(chart: Chart, label: str = "", include_house_lords: bool = True) -> str:
    """
    Compact structured text for feeding to the AI prediction engine.
    Optimized for LLM consumption.

    include_house_lords: emit the deterministic bhava-lord table. Should be True
    ONLY for the D-1 (natal) chart. Functional lordships ('my Nth lord') are a
    D-1-lagna concept and are fixed across all vargas — printing a separate lord
    table for each divisional chart invites the model to say things like "your
    7th lord in the D-9 is the Moon," which conflicts with the native's real
    (D-1) lordships and is exactly the confusion this parameter prevents.
    """
    lbl = label or chart.label
    lines = [f"\n=== {lbl} ==="]
    lines.append(f"Ascendant (Lagna): {chart.ascendant_sign} {chart.ascendant_degrees:.1f}°")

    # Deterministic house-lord table FIRST — this is the authoritative source
    # for "the Nth lord" and prevents the LLM from guessing lordships. Only the
    # D-1 natal chart carries it (see docstring).
    if include_house_lords:
        lines.append(format_house_lords(chart))

    # Group planets by house (occupants)
    by_house: dict[int, list[str]] = {}
    for name, p in chart.planets.items():
        h = p.house
        desc = f"{name}"
        if p.dignity != "neutral":
            desc += f"({p.dignity})"
        if p.retrograde and name not in ("Rahu","Ketu"):
            desc += "(R)"
        by_house.setdefault(h, []).append(desc)

    lines.append("Planet placements (occupants of each house):")
    for h in range(1, 13):
        if h in by_house:
            sign = SIGNS[chart.houses[h-1]] if (h-1) < len(chart.houses) else "?"
            lines.append(f"  House {h} ({sign}): {', '.join(by_house[h])}")

    # Key dignities
    special = [(n, p) for n, p in chart.planets.items() if p.dignity != "neutral"]
    if special:
        lines.append("\nKey Dignities:")
        for n, p in special:
            lines.append(f"  {n}: {p.dignity} in {p.sign} (House {p.house})")

    return "\n".join(lines)
