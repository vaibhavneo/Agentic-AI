"""
Verification for all 16 Shodasavarga divisional chart formulas.

Reference data: two independent real charts computed by AstroSage (Vaibhav's own
chart, 7 Jan 1981 Allahabad; and a second chart, 21 Jun 1986 Chandigarh), covering
Lagna + 9 planets across all 16 vargas. See chart/divisional.py module docstring
for full provenance notes. Source PDFs: ~/Desktop/Astrology Books/VedicReport*.pdf.

Run: python3 tests/test_divisional_charts.py
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from chart.calculator import VedicChartCalculator
import chart.divisional as dv


def sign_of(lon: float) -> int:
    """1-indexed sign number, Aries=1."""
    return int(lon / 30) % 12 + 1


CHARTS = [
    {
        "name": "Vaibhav (7 Jan 1981, Allahabad)",
        "dt_utc": datetime(1981, 1, 7, 9, 5, 0),
        "lat": 25 + 26 / 60,
        "lon": 81 + 50 / 60,
        "ref": {
            "D1":  [2, 9, 10, 10, 9, 6, 9, 6, 4, 10],
            "D2":  [4, 4, 4, 4, 4, 5, 5, 5, 5, 5],
            "D3":  [6, 5, 10, 2, 5, 10, 9, 10, 8, 2],
            "D4":  [5, 6, 10, 1, 6, 12, 9, 12, 10, 4],
            "D7":  [11, 2, 5, 6, 3, 3, 9, 3, 2, 8],
            "D9":  [2, 8, 11, 1, 9, 2, 1, 2, 9, 3],
            "D10": [2, 4, 8, 10, 6, 7, 9, 7, 6, 12],
            "D12": [7, 6, 12, 2, 8, 12, 9, 12, 11, 5],
            "D16": [12, 9, 4, 7, 11, 5, 9, 5, 10, 10],
            "D20": [6, 8, 5, 9, 11, 3, 6, 3, 1, 1],
            "D24": [3, 11, 9, 1, 3, 5, 6, 4, 6, 6],
            "D27": [4, 10, 9, 3, 1, 6, 2, 6, 2, 8],
            "D30": [12, 3, 6, 12, 7, 12, 1, 12, 12, 12],
            "D40": [1, 8, 3, 11, 1, 4, 3, 4, 7, 7],
            "D45": [1, 8, 10, 7, 2, 9, 11, 9, 4, 4],
            "D60": [5, 7, 10, 10, 4, 2, 12, 2, 5, 11],
        },
    },
    {
        "name": "Neha (21 Jun 1986, Chandigarh)",
        "dt_utc": datetime(1986, 6, 21, 5, 0, 0),
        "lat": 30 + 44 / 60,
        "lon": 76 + 47 / 60,
        "ref": {
            "D1":  [5, 3, 8, 9, 4, 11, 4, 8, 1, 7],
            "D4":  [8, 3, 2, 6, 4, 8, 7, 11, 1, 7],
            "D9":  [4, 8, 10, 9, 4, 3, 7, 7, 1, 7],
            "D12": [9, 5, 4, 8, 4, 10, 9, 12, 2, 8],
            "D16": [10, 12, 4, 12, 1, 8, 7, 10, 2, 2],
            "D20": [4, 8, 11, 12, 1, 3, 9, 4, 3, 3],
            "D24": [1, 9, 9, 3, 4, 3, 2, 12, 7, 7],
            "D27": [11, 12, 6, 2, 10, 8, 9, 7, 3, 9],
            "D30": [9, 11, 10, 7, 2, 7, 12, 6, 1, 1],
            "D40": [3, 8, 12, 3, 7, 2, 11, 9, 5, 5],
            "D45": [9, 5, 2, 3, 1, 11, 8, 9, 5, 5],
            "D60": [3, 2, 4, 6, 5, 7, 5, 6, 7, 1],
        },
    },
]

FORMULAS = {
    "D2": dv.calc_d2, "D3": dv.calc_d3, "D4": dv.calc_d4, "D7": dv.calc_d7,
    "D9": dv.calc_d9, "D10": dv.calc_d10, "D12": dv.calc_d12, "D16": dv.calc_d16,
    "D20": dv.calc_d20, "D24": dv.calc_d24, "D27": dv.calc_d27, "D30": dv.calc_d30,
    "D40": dv.calc_d40, "D45": dv.calc_d45, "D60": dv.calc_d60,
}


def main():
    calc = VedicChartCalculator()
    failures = []
    checks = 0

    for chart in CHARTS:
        jd = calc.to_julian_day(chart["dt_utc"])
        d1 = calc.build_d1(jd, chart["lat"], chart["lon"])
        lons = [
            d1.ascendant_longitude, d1.planets["Sun"].longitude, d1.planets["Moon"].longitude,
            d1.planets["Mars"].longitude, d1.planets["Mercury"].longitude, d1.planets["Jupiter"].longitude,
            d1.planets["Venus"].longitude, d1.planets["Saturn"].longitude, d1.planets["Rahu"].longitude,
            d1.planets["Ketu"].longitude,
        ]

        print(f"=== {chart['name']} ===")

        if "D1" in chart["ref"]:
            got = [sign_of(l) for l in lons]
            checks += 1
            if got != chart["ref"]["D1"]:
                failures.append((chart["name"], "D1", got, chart["ref"]["D1"]))
                print(f"  D1   FAIL  got={got}  want={chart['ref']['D1']}")
            else:
                print("  D1   OK")

        for key, want in chart["ref"].items():
            if key == "D1":
                continue
            fn = FORMULAS[key]
            got = [sign_of(fn(l)) for l in lons]
            checks += 1
            if got != want:
                failures.append((chart["name"], key, got, want))
                print(f"  {key:4s} FAIL  got={got}  want={want}")
            else:
                print(f"  {key:4s} OK")
        print()

    print(f"{checks} checks run, {len(failures)} failures")
    if failures:
        print("\nFAILURES:")
        for name, key, got, want in failures:
            print(f"  [{name}] {key}: got={got} want={want}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
