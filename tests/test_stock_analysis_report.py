"""
Report assembly (stock_analysis/report.py) and the agent contract — offline.

Run: python3 tests/test_stock_analysis_report.py

The summary is fixed sentences over computed fields, so it can only state
numbers the report holds; the data-lag note names a filing that SEC's XBRL
data does not yet include (TSMC's April 2026 20-F); and the agent declines
anything that files no 10-K/20-F, with the reason.
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


def test_data_lag_note():
    print("=== 1. SEC's XBRL data lagging the filings is named ===")
    from stock_analysis.report import data_lag
    st = {"annual": [{"end": "2024-12-31"}]}
    fl = {"latest_annual": {"form": "20-F", "filed": "2026-04-16", "accession": "B", "report_date": "2025-12-31"}}
    note = data_lag(st, fl)
    check("a filed year missing from XBRL is named", note and "2025-12-31" in note and "2024-12-31" in note)
    current = {"latest_annual": {"form": "20-F", "filed": "2025-04-17", "report_date": "2024-12-31"}}
    check("figures through the latest report's year → no note", data_lag(st, current) is None)


def test_summary_states_only_report_numbers():
    print("=== 2. the summary only restates computed fields ===")
    from stock_analysis.report import summarize
    from decision.narrative import validate_narrative
    rep = {
        "quality": {"available": True, "grade": "B", "score": 71.4,
                    "flags": [{"test": "Accrual ratio (Sloan)", "status": "CONCERN"}],
                    "context": {"revenue_growth": 0.142, "operating_margin": 0.33, "roic": 0.25}},
        "filings": {"available": True, "summary": {"concerns": 1, "watch": 2},
                    "flags": [{"severity": "CONCERN", "title": "Late-filing notice (NT 10-K)"}]},
        "valuation": {"multiples": {"available": True, "pe": 38.1, "fcf_yield": 0.028},
                      "implied_growth": {"reading": "Today's value implies free cash flow growing about 13.4% a year "
                                                    "for 10 years (at a 9% discount rate and 2.5% after)."}},
        "score": {"available": True, "score": 72.0, "version": "fundamentals-v2", "penalty": 13.0},
    }
    lines = summarize(rep)
    text = "\n".join(lines)
    check("grade and concern named", "grade B" in text and "Accrual ratio" in text)
    check("filing concern named", "Late-filing notice" in text)
    v = validate_narrative(text, rep)
    check("every number in the summary is in the report", v["unsupported_numbers"] == [], str(v["unsupported_numbers"]))


def test_agent_declines_non_filers():
    print("=== 3. the agent declines what files nothing ===")
    from mas.agents import stock_analysis as sa
    ok, why = sa.available("SPY", "ETF")
    check("an ETF is declined with a reason", not ok and "10-K" in why)
    ok, _ = sa.available("AAPL", "EQUITY")
    check("an equity is accepted", ok)


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
