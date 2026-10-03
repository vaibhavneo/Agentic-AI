"""
The pure parts of backtest/event_signals_eval.py and
backtest/survivorship_audit.py — offline.

Run: python3 tests/test_research_harnesses.py

A harness whose verdict rule or outcome classifier is wrong produces a
confident wrong conclusion, so both are pinned here on hand-built inputs.
"""
import sys
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {name:62s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    assert cond, name


def _q(ni):
    return {"end": "x", "values": {"net_income": {"value": ni}}}


def test_sue():
    print("=== 1. SUE (seasonal random walk) ===")
    from backtest import event_signals_eval as ev
    from unittest.mock import patch
    with patch("stock_analysis.statements.value", lambda q, c: q["values"][c]["value"]):
        # Newest first. Year-over-year changes alternate +1/-1 in history; the latest jumps by +5.
        hist = [10, 9, 8, 7]
        ni = [hist[i % 4] + (5 if i == 0 else 0) for i in range(13)]
        for i in range(1, 13):
            ni[i] += (1 if (i // 4) % 2 == 0 else 0)
        s = ev.sue([_q(v) for v in ni])
        check("a large latest surprise scores high", s is not None and s > 2, s)
        check("fewer than 13 quarters -> None", ev.sue([_q(1.0)] * 12) is None)
        check("flat history (zero dispersion) -> None", ev.sue([_q(1.0)] * 13) is None)


def test_promotion_rule():
    print("=== 2. the pre-stated promotion rule ===")
    from backtest.event_signals_eval import summarize, SIGNALS
    dates = [f"d{i}" for i in range(12)]
    rows = []
    for di, d in enumerate(dates):
        for k in range(10):
            fwd = float(k) + (1.6 if di % 2 else -1.6) * (k % 3)    # consistent but imperfect ranking
            rows.append({"symbol": f"S{k}", "date": d, "sue": float(k), "reaction": float(-k),
                         "rel_mom": float((k * 7 + di) % 10),
                         "fwd_63": fwd, "fwd_126": fwd, "fwd_252": fwd})
    v = summarize(rows, dates)["verdict"]
    check("signal ranked with the outcome every date -> promoted", v["sue"]["promote"])
    check("signal ranked against the outcome -> not promoted", not v["reaction"]["promote"])
    check("a verdict for every signal", set(v) == set(SIGNALS))


def test_outcome_classifier():
    print("=== 3. survivorship outcome from a company's own filings ===")
    from backtest.survivorship_audit import classify
    today = date(2026, 10, 1)
    base = [{"form": "DEF 14A", "filingDate": "2017-04-01"}, {"form": "10-K", "filingDate": "2018-02-20"}]
    live = classify(base + [{"form": "10-Q", "filingDate": "2026-08-01"}], today)
    check("recent 10-Q -> still filing", live["outcome"] == "STILL_FILING" and live["had_public_equity"])
    bk = classify(base + [{"form": "8-K", "filingDate": "2020-05-01", "items": "1.03,7.01"},
                          {"form": "10-Q", "filingDate": "2020-08-01"}], today)
    check("8-K Item 1.03 then silence -> bankruptcy", bk["outcome"] == "BANKRUPTCY", bk)
    acq = classify(base + [{"form": "DEFM14A", "filingDate": "2021-03-01"},
                           {"form": "10-Q", "filingDate": "2021-05-01"}], today)
    check("merger proxy then silence -> acquired", acq["outcome"] == "ACQUIRED")
    other = classify(base, today)
    check("silence with neither -> other stopped", other["outcome"] == "OTHER_STOPPED")
    sub = classify([{"form": "10-K", "filingDate": "2026-03-01"}], today)
    check("no 2017-18 proxy -> not public equity (debt-only filer)", not sub["had_public_equity"])
    old_bk = classify(base + [{"form": "8-K", "filingDate": "2009-06-01", "items": "1.03"}], today)
    check("a bankruptcy before 2018 is not this period's outcome", old_bk["outcome"] == "OTHER_STOPPED")


def test_successor_rules():
    print("=== 4. reorganization vs acquisition vs duplicate ===")
    from backtest.survivorship_audit import resolve_successors, successor_candidates
    titles = {1: "WALT DISNEY CO", 2: "Bunge Global SA", 3: "Smurfit Westrock plc", 4: "Fox Corp",
              5: "Applied Tech Data Systems Inc"}
    check("same name -> candidate", successor_candidates(["WALT DISNEY CO/"], titles, 99) == [1])
    check("adds only a generic word -> candidate", successor_candidates(["BUNGE LTD"], titles, 99) == [2])
    check("acquirer's name added -> not a successor", successor_candidates(["WestRock Co"], titles, 99) == [])
    check("partial overlap -> not a successor", successor_candidates(["TWENTY-FIRST CENTURY FOX, INC.",
                                                                      "TECH DATA CORP"], titles, 99) == [])
    rows = [{"cik": 10, "name": "WRKCo Inc.", "names": ["WRKCo Inc.", "WestRock Co"], "sic": "2631",
             "outcome": "ACQUIRED"},
            {"cik": 11, "name": "WestRock Co", "names": ["WestRock Co"], "sic": "2631", "outcome": "ACQUIRED"},
            {"cik": 12, "name": "TWDC Enterprises 18 Corp.", "names": ["TWDC Enterprises 18 Corp.", "WALT DISNEY CO/"],
             "sic": "7990", "outcome": "ACQUIRED"},
            {"cik": 13, "name": "BUNGELTD", "names": ["BUNGELTD", "BUNGE LTD"], "sic": "2070", "outcome": "ACQUIRED"}]
    sics = {1: "7990", 2: "9999", 11: "2631"}
    resolve_successors(rows, titles, {1: "DIS"}, lambda c: sics.get(c))
    out = {r["cik"]: r["outcome"] for r in rows}
    check("earlier registrant of a universe row -> duplicate", out[10] == "DUPLICATE")
    check("acquired by a differently named company stays acquired", out[11] == "ACQUIRED")
    check("holding-company reorganization -> reorganized, successor named",
          out[12] == "REORGANIZED" and rows[2]["successor"] == "WALT DISNEY CO (DIS)")
    check("same name in another industry -> not believed", out[13] == "ACQUIRED")


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
