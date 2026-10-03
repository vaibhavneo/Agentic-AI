"""
Analysts and insiders (stock_analysis/street.py, providers/finnhub_research.py) — offline.

Run: python3 tests/test_stock_analysis_street.py

Only open-market Form 4 trades count (grants, exercises, withholding and gifts
are compensation mechanics); three distinct buyers is a cluster; the beat rate
and analyst buy share are plain counts; and no key reads as waiting for the
named variable, never as empty data.
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {name:62s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    assert cond, name


def D(value, when, **extra):
    return {"value": value, "available_at": when, "period_end": when, "extra": extra}


def test_insiders_open_market_only():
    print("=== 1. insider trades: open market only, clusters ===")
    from stock_analysis.street import insiders
    data = [D(1000, "2026-09-01", name="A", code="P", price=10), D(500, "2026-08-01", name="B", code="P", price=10),
            D(300, "2026-07-01", name="C", code="P", price=10), D(-5000, "2026-09-10", name="D", code="S", price=11),
            D(20000, "2026-09-02", name="E", code="A", price=0), D(-800, "2026-09-03", name="F", code="F", price=11),
            D(900, "2025-01-01", name="G", code="P", price=9)]
    r = insiders(data, as_of="2026-10-01")
    check("grants and withholding excluded", r["purchases"] == 3 and r["sales"] == 1)
    check("trades outside 180 days excluded", "G" not in r["buyers"])
    check("three distinct buyers is a cluster", r["cluster_buying"] is True)
    check("purchase value = shares × price", r["purchase_value"] == 18000)


def test_surprises_and_recommendations():
    print("=== 2. beat rate and analyst buy share ===")
    from stock_analysis.street import surprises, recommendations
    s = surprises([D(1.2, "2026-06-30", estimate=1.0, surprise_pct=20.0), D(0.9, "2026-03-31", estimate=1.0,
                                                                         surprise_pct=-10.0)])
    check("beat 1 of 2", s["beat_rate"] == 0.5 and s["n"] == 2)
    check("average surprise", s["avg_surprise_pct"] == 5.0)
    recs = [D(10, f"2026-{m:02d}-01", strongBuy=b, buy=2, hold=4, sell=1, strongSell=0)
            for m, b in ((9, 5), (8, 4), (7, 3), (6, 1))]
    r = recommendations(recs)
    check("buy share now = 7/12", r["buy_share"] == round(7 / 12, 3))
    check("change vs three months earlier", r["change_3m"] == round(7 / 12 - 3 / 8, 3))


def test_fiscal_quarter_label_not_vendor_calendar_date():
    print("=== fiscal label ===")
    from stock_analysis.street import surprises
    r = surprises([{"value": 2.22, "period_end": "2026-09-30",
                    "extra": {"estimate": 2.14, "surprise_pct": 3.8, "year": 2027, "quarter": 2}}])
    q = r["quarters"][0]
    check("Nvidia's Jul-2026 quarter shows as FY2027 Q2, not 2026-09-30", q["fiscal"] == "FY2027 Q2"
          and q["period"] == "2026-09-30")
    r = surprises([{"value": 1.0, "period_end": "2026-06-30", "extra": {"estimate": 0.9}}])
    check("no fiscal fields -> no invented label", r["quarters"][0]["fiscal"] is None)


def test_no_key_says_so():
    print("=== 3. no key: waiting for the named variable ===")
    import os
    from stock_analysis import street
    saved = os.environ.pop("FINNHUB_API_KEY", None)
    import financial_data.keys as K
    orig = K._lookup
    K._lookup = lambda var: None
    try:
        r = street.build_street("AAPL")
        check("unavailable, naming FINNHUB_API_KEY", r["available"] is False and "FINNHUB_API_KEY" in r["reason"],
              r.get("reason"))
    finally:
        K._lookup = orig
        if saved:
            os.environ["FINNHUB_API_KEY"] = saved


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
