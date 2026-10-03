"""
Key-gated vendor providers (alphavantage.py, fmp.py) — offline, urlopen stubbed.

Run: python3 tests/test_vendor_providers.py

Alpha Vantage reports rate limits and plan restrictions IN-BAND (HTTP 200 with
a "Note"/"Information" body); FMP uses HTTP 402 for paid endpoints. Both must
become a named failure, never an empty success; a missing key names its
variable.
"""
import io
import json
import os
import sys
import tempfile
import urllib.error
import warnings
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {name:62s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    assert cond, name


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _with_key(var):
    import financial_data.keys as K
    return patch.object(K, "_lookup", lambda v: "test-key" if v == var else None)


def test_alphavantage():
    print("=== 1. Alpha Vantage ===")
    from financial_data import cache
    import financial_data.providers.alphavantage as av
    with patch.object(cache, "CACHE_DIR", Path(tempfile.mkdtemp())), _with_key("ALPHAVANTAGE_API_KEY"):
        note = {"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."}
        with patch("urllib.request.urlopen", lambda *a, **k: _Resp(json.dumps(note).encode())):
            r = av.fetch("events", ["AAPL"], concepts=["earnings_surprise"])
        check("in-band rate-limit note is a named failure", not r["data"] and "rate limit" in r["unavailable"][0]["reason"])
        body = {"symbol": "AAPL", "quarterlyEarnings": [
            {"fiscalDateEnding": "2026-06-30", "reportedDate": "2026-07-30", "reportedEPS": "1.60",
             "estimatedEPS": "1.50", "surprisePercentage": "6.67"}]}
        with patch("urllib.request.urlopen", lambda *a, **k: _Resp(json.dumps(body).encode())):
            r = av.fetch("events", ["MSFT"], concepts=["earnings_surprise"])
        d = r["data"][0]
        check("reported vs estimated EPS, dated by the report", d["value"] == 1.6 and d["extra"]["estimate"] == 1.5
              and d["available_at"].startswith("2026-07-30"))


def test_fmp_paid_endpoint():
    print("=== 2. FMP paid endpoint ===")
    from financial_data import cache
    import financial_data.providers.fmp as fmp

    def raise402(*a, **k):
        raise urllib.error.HTTPError("u", 402, "Payment Required", {}, None)
    with patch.object(cache, "CACHE_DIR", Path(tempfile.mkdtemp())), _with_key("FMP_API_KEY"), \
            patch("urllib.request.urlopen", raise402):
        r = fmp.fetch("filings", ["AAPL"], concepts=["call_transcript"], year=2026, quarter=2)
    check("HTTP 402 → 'needs a paid plan'", "paid plan" in r["unavailable"][0]["reason"])


def test_missing_key_names_variable():
    print("=== 3. a missing key names its variable ===")
    import financial_data.keys as K
    import financial_data.providers.fmp as fmp
    with patch.object(K, "_lookup", lambda v: None):
        try:
            fmp.fetch("events", ["AAPL"], concepts=["earnings_surprise"])
            raised = None
        except Exception as e:
            raised = str(e)
    check("FMP_API_KEY named", raised is not None and "FMP_API_KEY" in raised, raised)


def test_surprise_source_priority():
    print("=== 4. earnings history: longest source first ===")
    import stock_analysis.street as st
    calls = []

    def fake(kind, symbol, concept, provider=st.PROVIDER):
        calls.append(provider)
        if provider == "alphavantage":
            return {"data": [], "error": "waiting for ALPHAVANTAGE_API_KEY (free at alphavantage.co)", "provider": provider}
        return {"data": [{"value": 1.0, "period_end": "2026-06-30", "extra": {"estimate": 0.9}}], "provider": provider}
    with patch.object(st, "_get", fake):
        r = st._surprise_source("AAPL")
    check("falls through to FMP when Alpha Vantage has no key", r["provider"] == "fmp" and calls == ["alphavantage", "fmp"])
    check("the skipped source is reported", "ALPHAVANTAGE_API_KEY" in r["tried"][0])


def test_transcript_without_keys():
    print("=== 5. transcript with no vendor key ===")
    import financial_data.keys as K
    from stock_analysis.transcripts import build_transcript
    stm = {"quarters": [{"end": "2026-06-27", "label": "FY2026 Q3"}]}
    with patch.object(K, "_lookup", lambda v: None):
        t = build_transcript("AAPL", stm, summarize=False)
    check("unavailable, naming both keys", not t["available"] and "ALPHAVANTAGE_API_KEY" in t["reason"]
          and "FMP_API_KEY" in t["reason"], t.get("reason"))


def test_cache_ceiling():
    print("=== 6. the cache stays under its ceiling ===")
    import time as _t
    from financial_data import cache
    root = Path(tempfile.mkdtemp())
    for i in range(10):
        f = root / "p" / "k" / f"f{i}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x" * 1000)
        os.utime(f, (_t.time() - 1000 + i, _t.time() - 1000 + i))      # f0 oldest
    (root / "p" / "k" / "keep.db").write_text("y" * 5000)               # not a cache file
    r = cache.prune(max_bytes=5000, target=0.8, root=root)
    left = sorted(p.name for p in (root / "p" / "k").glob("*.json"))
    check("pruned down to the target", r["bytes"] <= 4000 and r["pruned"] == 6, r)
    check("oldest written go first", left == ["f6.json", "f7.json", "f8.json", "f9.json"], left)
    check("non-cache files untouched", (root / "p" / "k" / "keep.db").exists())
    check("no ceiling -> nothing deleted", cache.prune(max_bytes=0, root=root)["pruned"] == 0)


def test_alphavantage_empty_transcript_is_retried_and_calls_are_spaced():
    print("=== 7. an empty transcript is held a day, not a month; calls are spaced ===")
    import time as _t
    from financial_data import cache
    import financial_data.providers.alphavantage as av
    calls = []

    def fake(req, timeout=30):
        calls.append(_t.monotonic())
        return _Resp(json.dumps({"symbol": "NVDA", "quarter": "2027Q2", "transcript": []}).encode())
    root = Path(tempfile.mkdtemp())
    with patch.object(cache, "CACHE_DIR", root), _with_key("ALPHAVANTAGE_API_KEY"), \
            patch("urllib.request.urlopen", fake), patch.object(av, "MIN_SPACING_SEC", 0.3):
        r = av.fetch("filings", ["NVDA"], concepts=["call_transcript"], quarter="2027Q2")
        check("empty answer is a named 'no transcript', not data", not r["data"] and "no transcript" in
              r["unavailable"][0]["reason"])
        key = "function-EARNINGS_CALL_TRANSCRIPT_quarter-2027Q2_symbol-NVDA"
        check("held under the short-lived key only", cache.get("alphavantage", "api", key) is None
              and cache.get("alphavantage", "api", key + "__empty") is not None)
        av.fetch("filings", ["NVDA"], concepts=["call_transcript"], quarter="2027Q2")
        check("within the day: served from the short cache (no new call)", len(calls) == 1)
        cache.put("alphavantage", "api", key, {"transcript": []})        # what the old code cached for 30 days
        p = cache.path_for("alphavantage", "api", key + "__empty")
        os.utime(p, (_t.time() - 2 * 86400, _t.time() - 2 * 86400))      # the day has passed
        av.fetch("filings", ["NVDA"], concepts=["call_transcript"], quarter="2027Q2")
        check("a month-cached empty answer is not trusted; asked again", len(calls) == 2)
        check("second call waited for the spacing", calls[1] - calls[0] >= 0.3, round(calls[1] - calls[0], 2))


def test_transcript_falls_back_to_the_previous_call():
    print("=== 8. latest call not out yet -> the one before, saying so ===")
    import stock_analysis.transcripts as tr
    seen = []

    def fake_get(kind, symbol, provider=None, concepts=None, **kw):
        seen.append((provider, kw.get("quarter")))
        if provider == "alphavantage" and kw.get("quarter") == "2027Q1":
            return {"data": [{"value": "Operator: welcome", "source": {"provider": "alphavantage"}}]}
        if provider == "fmp":
            raise RuntimeError("FMP_API_KEY is not set")
        return {"data": [], "unavailable": [{"reason": "no transcript for NVDA " + kw.get("quarter", "")}]}
    with patch("financial_data.gateway.get", fake_get):
        t = tr.build_transcript("NVDA", {"quarters": [{"label": "FY2027 Q2"}]}, summarize=False)
    check("FY2027 Q1 shown", t["available"] and t["fiscal_quarter"] == "FY2027 Q1", t)
    check("and the reader is told why", "FY2027 Q2 call is not available" in t.get("note", ""))
    check("a provider waiting for its key is asked once", sum(1 for p, _ in seen if p == "fmp") == 1, seen)
    check("Q1 of a year falls back to Q4 of the year before", tr._previous(2027, 1) == (2026, 4))


def test_surprise_stats_use_recent_quarters():
    print("=== 9. beat rate over the last two years, not since 1999 ===")
    from stock_analysis.street import surprises
    old = [{"value": 0.03, "period_end": f"{1999 + i}-03-31", "extra": {"estimate": 0.02, "surprise_pct": 50.0}}
           for i in range(20)]
    new = [{"value": 1.0, "period_end": f"2025-{m:02d}-28", "extra": {"estimate": 1.02, "surprise_pct": -2.0}}
           for m in range(1, 9)]
    r = surprises(old + new)
    check("window is the last 8", r["n"] == 8 and r["n_history"] == 28 and r["window"] == "last 8 quarters")
    check("old outliers do not move the average", r["avg_surprise_pct"] == -2.0 and r["beat_rate"] == 0.0)


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
