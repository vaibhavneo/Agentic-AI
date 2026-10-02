"""
Fundamentals findings as decision evidence (decision/filings_evidence.py) — offline.

Run: python3 tests/test_filings_evidence.py

A restatement notice or ineffective controls is DECISIVE bearish risk; a high
earnings-quality grade is context only (no measured return edge); absent
findings are said, not skipped; and no report means no evidence at all.
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


def _rep(flags=(), grade="B", score=70.0, tests=()):
    return {"available": True, "as_of": "2026-10-01",
            "filings": {"available": True, "flags": list(flags)},
            "quality": {"available": True, "grade": grade, "score": score, "flags": [], "tests": list(tests)}}


def test_findings_become_evidence():
    print("=== 1. filing findings and quality grade as evidence ===")
    from decision.filings_evidence import evidence_from_fundamentals
    bad = _rep(flags=[{"severity": "CONCERN", "code": "8K_ITEM_4_02", "title": "Non-reliance"},
                      {"severity": "WATCH", "code": "8K_ITEM_4_01", "title": "Auditor change"}], grade="F", score=20)
    items = {e.metric: e for e in evidence_from_fundamentals(bad)}
    check("a restatement notice is DECISIVE bearish risk",
          items["filing_red_flags"].direction == "BEARISH" and items["filing_red_flags"].decision_relevance == "DECISIVE")
    check("grade F is bearish, labelled backtested-only",
          items["earnings_quality"].direction == "BEARISH"
          and items["earnings_quality"].validation_status == "BACKTESTED_ONLY")
    good = {e.metric: e for e in evidence_from_fundamentals(_rep(grade="A", score=90))}
    check("grade A is context, not a bullish claim", good["earnings_quality"].direction == "NOT_DIRECTIONAL")
    check("no findings is stated", "No red flags" in good["filing_red_flags"].observation)
    check("no report → no evidence", evidence_from_fundamentals(None) == []
          and evidence_from_fundamentals({"available": False}) == [])


def test_monitoring_checks():
    print("=== 2. what to watch in the next filing ===")
    from decision.filings_evidence import monitoring_checks
    rep = _rep(tests=[{"key": "receivables", "name": "Receivables vs sales (DSO)", "status": "CONCERN",
                       "display": "51 days"}, {"key": "piotroski", "name": "Piotroski", "status": "WATCH"}])
    checks = monitoring_checks(rep)
    check("filing watcher always listed", "New SEC filings" in checks[0]["what"])
    check("a receivables concern is re-tested on the next 10-Q",
          any("Receivables" in c["what"] for c in checks) and not any("Piotroski" in c["what"] for c in checks))


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
