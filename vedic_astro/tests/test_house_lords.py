"""
Evaluation for deterministic house-lordship computation (chart/formatter.py).

The classical Parasari house-lord table for every one of the 12 ascendants is
fixed and well-known. This test hard-codes the ground truth and checks our
computed table against it for ALL 12 lagnas — the bug the user hit (Venus
mis-labeled as 7th lord, Jupiter as 5th lord for a Taurus lagna) would fail
here loudly.

Run: python3 tests/test_house_lords.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from chart.formatter import house_lordships
from chart.calculator import SIGNS

FAILURES = []

# Ground truth: for each ascendant sign, the lord of each house 1..12.
# (Whole-Sign houses; standard Vedic sign rulerships.)
SIGN_RULER = {
    "Aries":"Mars","Taurus":"Venus","Gemini":"Mercury","Cancer":"Moon",
    "Leo":"Sun","Virgo":"Mercury","Libra":"Venus","Scorpio":"Mars",
    "Sagittarius":"Jupiter","Capricorn":"Saturn","Aquarius":"Saturn","Pisces":"Jupiter",
}


class Stub:
    """Minimal chart stub — house_lordships only needs `.houses`."""
    def __init__(self, asc_idx):
        self.houses = [(asc_idx + i) % 12 for i in range(12)]
        self.planets = {}


def expected_lords(asc_idx):
    """The correct lord for each house 1..12 given the ascendant index."""
    return {h: SIGN_RULER[SIGNS[(asc_idx + h - 1) % 12]] for h in range(1, 13)}


def check(name, cond, detail=""):
    print(f"  {name:52s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_all_twelve_ascendants():
    for asc_idx, asc_sign in enumerate(SIGNS):
        by_house, _ = house_lordships(Stub(asc_idx))
        exp = expected_lords(asc_idx)
        ok = all(by_house[h][1] == exp[h] for h in range(1, 13))
        detail = "" if ok else f"got {[by_house[h][1] for h in range(1,13)]}"
        check(f"{asc_sign} lagna: all 12 house lords correct", ok, detail)


def test_taurus_user_facts():
    """The exact facts from the user's bug report."""
    print("\n=== Taurus lagna — user-reported facts ===")
    by_house, by_lord = house_lordships(Stub(1))  # Taurus = idx 1
    check("Venus is Lagnesh (1st lord)", 1 in by_lord.get("Venus", []))
    check("Venus is NOT the 7th lord", 7 not in by_lord.get("Venus", []))
    check("7th lord is Mars", by_house[7][1] == "Mars")
    check("5th lord is Mercury, not Jupiter", by_house[5][1] == "Mercury")
    check("Jupiter rules 8th and 11th", set(by_lord.get("Jupiter", [])) == {8, 11})
    check("Jupiter does NOT rule the 5th", 5 not in by_lord.get("Jupiter", []))


if __name__ == "__main__":
    print("=== test_all_twelve_ascendants ===")
    test_all_twelve_ascendants()
    test_taurus_user_facts()

    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS")
