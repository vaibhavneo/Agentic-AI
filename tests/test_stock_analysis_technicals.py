"""
Technicals tied to the filing calendar (stock_analysis/technicals.py) — offline.

Run: python3 tests/test_stock_analysis_technicals.py

The earnings reaction is the stock's move from the close BEFORE the release to
the close the trading day AFTER, net of the market's move over the same days;
a release on a non-trading day is priced from the next session.
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


def _df(values, start="2025-01-01"):
    import pandas as pd
    idx = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({"Close": values}, index=idx)


def test_reaction_net_of_market():
    print("=== 1. reaction = stock move minus market move ===")
    from stock_analysis.technicals import earnings_reactions
    stock = [100.0] * 30 + [110.0] * 40          # jumps on day 30
    market = [100.0] * 30 + [102.0] * 40
    s, m = _df(stock), _df(market)
    day = str(s.index[30])[:10]
    r = earnings_reactions(s, m, [day])
    check("one release measured", r["n"] == 1)
    check("10% stock move minus 2% market = 8%", abs(r["releases"][0]["reaction"] - 0.08) < 1e-9,
          str(r["releases"][0]))
    check("flat afterwards → zero drift", abs(r["releases"][0]["drift_20d"]) < 1e-9)


def test_release_on_weekend_uses_next_session():
    print("=== 2. a release on a non-trading day ===")
    from stock_analysis.technicals import earnings_reactions
    s = _df([100.0] * 10 + [90.0] * 30, start="2025-01-06")   # Monday start
    sat = "2025-01-18"                                          # day 10 is Monday 2025-01-20
    r = earnings_reactions(s, None, [sat])
    check("priced from the next trading session", r["n"] == 1 and abs(r["releases"][0]["raw_move"] + 0.10) < 1e-9,
          str(r["releases"][0]))


def test_price_context():
    print("=== 3. trend and returns ===")
    from stock_analysis.technicals import price_context, sector_etf
    up = _df([100 + i for i in range(300)])
    c = price_context(up)
    check("steady rise is an uptrend", c["trend"] == "uptrend" and c["above_200d"])
    check("12-month return computed", abs(c["returns"]["12m"] - (399 / 147 - 1)) < 1e-4, str(c["returns"]["12m"]))
    check("no drawdown in a steady rise", c["max_drawdown_1y"] == 0)
    check("semiconductors benchmark to XLK", sector_etf("3674") == "XLK")
    check("banks benchmark to XLF", sector_etf("6021") == "XLF")


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
