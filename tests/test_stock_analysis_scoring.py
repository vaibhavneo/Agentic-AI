"""
Fundamentals v2 score and its wiring into the pillar (stock_analysis/scoring.py,
backtest/pillars.py) — offline; the live v2 call is stubbed.

Run: python3 tests/test_stock_analysis_scoring.py

Pins: the bands and penalty caps; shadow mode leaves the composite exactly as
v1 scored it while recording v2; v2 mode scores the pillar with v2 and the v2
core weights and records which scorer it was; v2 unavailable falls back to v1
and says so; under pytest v2 is never computed unless a test asks.
"""
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {name:62s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    assert cond, name


def _blk(**vals):
    return {"end": "2026-06-30", "values": {k: {"value": float(v)} for k, v in vals.items()}}


def test_components_and_penalty():
    print("=== 1. v2 components, bands and penalty caps ===")
    from stock_analysis.scoring import score_components
    t = _blk(revenue=1000, operating_income=200, net_income=150, pretax_income=190, income_tax=40, equity=500,
             long_term_debt=250, cash=100, operating_cash_flow=180, capex=30)
    p = _blk(revenue=900, equity=480)
    st = {"ttm": t, "ttm_prior": p, "annual": []}
    q = {"grade": "B", "score": 70.0}
    mkt = {"available": True, "market_cap_usd": 3000.0, "fx": {"rate": 1.0}}
    r = score_components(st, q, "industrial", mkt, [])
    check("quality sub = the earnings-quality score", r["subs"]["quality"] == 70.0)
    check("growth: 50 + 11.1% × 250", abs(r["subs"]["growth"] - (50 + (1000 / 900 - 1) * 250)) < 0.1)
    check("cash return: 30 + FCF yield 5% × 1000 = 80", r["subs"]["cash_return"] == 80.0)
    check("balance sheet: 100 − D/E 0.5 × 33.3", abs(r["subs"]["balance_sheet"] - (100 - 0.5 * 33.3)) < 0.1)
    flags = [{"severity": "CONCERN", "title": "x"}] * 4 + [{"severity": "WATCH", "title": "y"}] * 5
    r2 = score_components(st, q, "industrial", mkt, flags)
    check("penalty caps: 25 for concerns + 9 for watches", r2["penalty"] == 34.0)
    r3 = score_components(st, {"grade": None, "score": None}, "bank", None, [])
    check("a bank: quality and balance sheet not scored, weight renormalized",
          r3["subs"]["quality"] is None and r3["subs"]["balance_sheet"] is None and r3["coverage"] < 1.0)


def _meters():
    from test_pillars import make_df, live_meters
    return live_meters(make_df("up"))


V2 = {"available": True, "score": 91.0, "subs": {"quality": 90.0}, "penalty": 0.0, "coverage": 1.0,
      "version": "fundamentals-v2", "quality_grade": "A", "period_end": "2026-06-30", "working": {}}


def _run(mode, v2_result):
    import backtest.pillars as P
    os.environ["STOCK_ANALYSIS_SCORER_IN_TESTS"] = "1"
    os.environ["FUNDAMENTALS_SCORER"] = mode
    orig = P._v2_fundamentals
    P._v2_fundamentals = lambda ticker, pit, price: v2_result
    try:
        ind, ss, algo = _meters()
        pit = {"available": True, "ratios": {"net_margin": {"value": 0.10}, "return_on_equity": {"value": 0.20},
                                              "debt_to_equity": {"value": 0.5}, "operating_margin": {"value": 0.15}}}
        return P.compute_pillar_scores("TEST", ind, ss, algo, {}, pit=pit, strict_fundamentals=True)
    finally:
        P._v2_fundamentals = orig
        os.environ.pop("STOCK_ANALYSIS_SCORER_IN_TESTS", None)
        os.environ.pop("FUNDAMENTALS_SCORER", None)


def test_modes():
    print("=== 2. v1 / shadow / v2 in the pillar ===")
    v1 = _run("v1", V2)
    sh = _run("shadow", V2)
    v2 = _run("v2", V2)
    fb = _run("v2", None)
    f1, fs, f2 = v1["pillars"]["fundamentals"], sh["pillars"]["fundamentals"], v2["pillars"]["fundamentals"]
    check("shadow: pillar score identical to v1", fs["score"] == f1["score"])
    check("shadow: composite identical to v1", sh["composite"] == v1["composite"])
    check("shadow: v2 recorded alongside", fs["inputs"]["v2_shadow"]["score"] == 91.0)
    check("v2: pillar scored by v2", f2["score"] == 91.0)
    check("v2: v1 kept for comparison", f2["inputs"]["v1_shadow"] == round(f1["score"], 1))
    check("v2: v2 core weights", v2["weights"]["fundamentals"] == 0.40 and v2["weight_source"] == "CORE_WEIGHTS_V2",
          str(v2["weights"]))
    check("scorer recorded on the snapshot", v2["fundamentals_scorer_version"] == "fundamentals-v2"
          and v1["fundamentals_scorer_version"] == "fundamentals-v1")
    check("v2 unavailable: falls back to v1 and says so",
          fb["pillars"]["fundamentals"]["score"] == f1["score"]
          and "fundamentals_v2_unavailable_fell_back_to_v1" in fb["pillars"]["fundamentals"]["flags"])


def test_never_under_pytest_by_default():
    print("=== 3. no live v2 under pytest unless asked ===")
    import backtest.pillars as P
    os.environ["FUNDAMENTALS_SCORER"] = "v2"
    try:
        check("pytest without opt-in reads v1", P.fundamentals_scorer() == "v1")
    finally:
        os.environ.pop("FUNDAMENTALS_SCORER", None)


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
