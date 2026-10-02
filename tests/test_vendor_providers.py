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


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
