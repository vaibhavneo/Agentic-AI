"""
Filing watcher and screener (stock_analysis/watcher.py, screener.py) — offline.

Run: python3 tests/test_stock_analysis_watch.py

The first look at a name records what is on file without alerting (except the
last three days); a later NT 10-K or 8-K Item 4.02 raises a CONCERN once,
never twice; and the screener filters are plain arithmetic over its rows.
"""
import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["STOCK_ANALYSIS_STATE_DIR"] = tempfile.mkdtemp()

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {name:62s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    assert cond, name


def F(acc, form, filed, items=""):
    return {"accession": acc, "form": form, "filed": filed, "items": items, "url": f"u/{acc}"}


def test_watcher_alerts_once_and_baselines():
    print("=== 1. baseline, then alerts on new filings, once ===")
    import stock_analysis.watcher as w
    import stock_analysis.filings as fl
    on_file = [F("OLD-1", "NT 10-K", "2019-03-01"), F("OLD-2", "8-K", "2026-09-29", "4.01")]
    orig = fl.filing_index
    fl.filing_index = lambda t, as_of=None, fresh=False: {"filings": list(on_file)}
    w._rescore = lambda t: None
    try:
        r1 = w.check(["TEST"], today="2026-10-01")
        codes = [a["code"] for a in r1["new_alerts"]]
        check("first look: a 2019 notice is NOT alerted", "LATE_FILING" not in codes)
        check("first look: a filing from 2 days ago IS alerted", "8K_ITEM_4_01" in codes)
        on_file.insert(0, F("NEW-1", "8-K", "2026-10-05", "4.02,9.01"))
        on_file.insert(0, F("NEW-2", "NT 10-Q", "2026-10-06"))
        r2 = w.check(["TEST"], today="2026-10-06")
        sev = {a["code"]: a["severity"] for a in r2["new_alerts"]}
        check("Item 4.02 → CONCERN", sev.get("8K_ITEM_4_02") == "CONCERN")
        check("late filing → CONCERN", sev.get("LATE_FILING") == "CONCERN")
        r3 = w.check(["TEST"], today="2026-10-07")
        check("nothing new → no repeat alerts", r3["new_alerts"] == [])
        listed = w.alerts()
        check("alerts listed, concerns first", listed[0]["severity"] == "CONCERN" and len(listed) == 3)
        check("mark all read", w.mark_read() == 3 and w.alerts(unread_only=True) == [])
    finally:
        fl.filing_index = orig


def test_screener_filters():
    print("=== 2. screener filters ===")
    from stock_analysis.screener import screen
    rows = [{"ticker": "A", "available": True, "score": 80, "quality_grade": "A", "pe": 20, "fcf_yield": 0.05,
             "filing_concerns": 0, "revenue_growth": 0.1},
            {"ticker": "B", "available": True, "score": 60, "quality_grade": "C", "pe": 40, "fcf_yield": 0.01,
             "filing_concerns": 2, "revenue_growth": 0.3},
            {"ticker": "C", "available": True, "score": None, "quality_grade": None, "pe": None,
             "filing_concerns": 0},
            {"ticker": "D", "available": False}]
    check("sorted by score, unscored last", [r["ticker"] for r in screen(rows)] == ["A", "B", "C"])
    check("min score", [r["ticker"] for r in screen(rows, min_score=70)] == ["A"])
    check("no filing concerns", "B" not in [r["ticker"] for r in screen(rows, no_filing_concerns=True)])
    check("grade filter", [r["ticker"] for r in screen(rows, grades=["C"])] == ["B"])
    check("max P/E drops names without a P/E", [r["ticker"] for r in screen(rows, max_pe=30)] == ["A"])


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
