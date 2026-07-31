"""
Deterministic checks for the gochara (transit) + dasha-bhukti timing engine
(chart/transits.py + calculator.calc_dasha_bhukti).

Transits reuse the SAME Swiss Ephemeris calc_planet as the natal chart, so the
real risk isn't ephemeris accuracy — it's the natal-relative bookkeeping (house
counting from Moon/Lagna, Sade Sati classification), the antardasha math, and the
target-date parser. Those are what this test pins down, against hand-computed
values for a fixed birth chart and a fixed evaluation date.

Run: python3 tests/test_transits.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from chart.calculator import VedicChartCalculator
from chart.transits import (
    _house_from,
    _sade_sati_note,
    compute_transit_positions,
    build_dasha_bhukti_context,
    extract_target_times,
)
from geocoder import parse_birth_datetime

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, got, want))
        print(f"  FAIL {name}: got={got!r} want={want!r}")
    else:
        print(f"  OK   {name}")


def main():
    calc = VedicChartCalculator()
    utc = parse_birth_datetime("1985-12-13", "08:13", 5.5)
    jd = calc.to_julian_day(utc)
    d1 = calc.build_d1(jd, 25.4381, 81.8338)
    moon_sign = d1.planets["Moon"].sign_index

    print("== house counting (whole-sign, 1-indexed) ==")
    check("same sign -> 1st house", _house_from(5, 5), 1)
    check("next sign -> 2nd house", _house_from(6, 5), 2)
    check("wrap-around (Aries from Aquarius) -> 3rd", _house_from(0, 10), 3)
    check("12th house", _house_from(4, 5), 12)

    print("\n== Sade Sati classification (relative to natal Moon) ==")
    # Saturn in the Moon sign -> peak; 12th before -> rising; 2nd after -> setting.
    check("peak (Saturn on Moon)", "Peak" in _sade_sati_note(moon_sign, moon_sign), True)
    check("rising (12th from Moon)", "Rising" in _sade_sati_note((moon_sign - 1) % 12, moon_sign), True)
    check("setting (2nd from Moon)", "Setting" in _sade_sati_note((moon_sign + 1) % 12, moon_sign), True)
    check("ashtama (8th from Moon)", "Ashtama" in _sade_sati_note((moon_sign + 7) % 12, moon_sign), True)
    check("none (7th from Moon)", "Not in Sade Sati" in _sade_sati_note((moon_sign + 6) % 12, moon_sign), True)

    print("\n== transit positions: all 9 grahas, Ketu opposite Rahu ==")
    tp = compute_transit_positions(calc, datetime(2026, 7, 26, tzinfo=timezone.utc))
    check("9 bodies computed", sorted(tp.keys()) ==
          sorted(["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]), True)
    check("Ketu is 180 from Rahu",
          round((tp["Ketu"].longitude - tp["Rahu"].longitude) % 360, 1), 180.0)

    print("\n== dasha-bhukti timeline is grounded & ordered ==")
    tl = calc.calc_dasha_bhukti(jd, d1.planets["Moon"].longitude)
    # Native is in Mars Mahadasha across the mid-2020s (verified: Mars 2022->2029).
    mars_md = [md for md in tl if md["lord"] == "Mars" and md["start"] < 2026 < md["end"]]
    check("Mars MD active in 2026", len(mars_md) == 1, True)
    md = mars_md[0]
    # Bhuktis tile the MD with no gaps and in Vimshottari order from the MD lord.
    b = md["bhuktis"]
    check("first bhukti is MD lord (Mars-Mars)", b[0]["lord"], "Mars")
    check("9 bhuktis", len(b), 9)
    contiguous = all(abs(b[i]["end"] - b[i + 1]["start"]) < 1e-6 for i in range(8))
    check("bhuktis contiguous", contiguous, True)
    check("bhuktis span the MD", abs(b[0]["start"] - md["start"]) < 1e-6 and
          abs(b[-1]["end"] - md["end"]) < 1e-6, True)

    print("\n== target-date extraction ==")
    now = datetime(2026, 7, 26)
    check("no date -> now only", len(extract_target_times("will she travel?", now)), 1)
    yr = extract_target_times("anything in 2027?", now)
    check("explicit year parsed", len(yr) == 2 and yr[1][1].year, 2027)
    nx = extract_target_times("what about next year?", now)
    check("next year -> 2027", nx[1][1].year, 2027)
    rel = extract_target_times("in 3 years from now?", now)
    check("relative +3 years -> 2029", rel[1][1].year, 2029)

    print(f"\n{len(failures)} failures")
    if failures:
        for n, g, w in failures:
            print(f"  [{n}] got={g!r} want={w!r}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
