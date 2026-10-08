"""The /api/recommendation cache: TTL rules, no cached failures, and a hit
neither rebuilds nor freezes another snapshot."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents import rec_cache as C   # noqa: E402


@pytest.fixture(autouse=True)
def fresh():
    C.clear()
    yield
    C.clear()


def ny(*a):
    return datetime(*a, tzinfo=C.NY)


def test_ttl_is_short_in_market_hours_and_lasts_until_the_next_open_otherwise():
    assert C.ttl_seconds(ny(2026, 10, 7, 11, 0)) == 15 * 60                       # Wednesday 11:00
    assert C.ttl_seconds(ny(2026, 10, 7, 8, 0)) == 90 * 60                        # before the open
    assert C.ttl_seconds(ny(2026, 10, 7, 17, 0)) == (16 * 60 + 30) * 60           # → Thursday 09:30
    assert C.ttl_seconds(ny(2026, 10, 9, 17, 0)) == (64 * 60 + 30) * 60           # Friday → Monday 09:30
    assert C.ttl_seconds(ny(2026, 10, 10, 12, 0)) == (45 * 60 + 30) * 60          # Saturday → Monday


def test_a_hit_returns_a_copy_marked_as_cached_and_failures_are_never_cached():
    C.put("aapl", "5y", {"ticker": "AAPL", "composite": 72.3})
    hit = C.get("AAPL", "5y")
    assert hit["composite"] == 72.3 and hit["cache"]["hit"] is True
    hit["composite"] = 0
    assert C.get("AAPL", "5y")["composite"] == 72.3                               # callers can't poison it
    assert C.get("AAPL", "1y") is None                                            # period is part of the key
    C.put("MSFT", "5y", {"error": "No data"})
    assert C.get("MSFT", "5y") is None


def test_expired_entries_are_dropped(monkeypatch):
    C.put("AAPL", "5y", {"ticker": "AAPL"})
    real = C.time.time
    monkeypatch.setattr(C.time, "time", lambda: real() + 10 ** 7)
    assert C.get("AAPL", "5y") is None


def test_the_endpoint_serves_a_repeat_without_rebuilding_or_refreezing(monkeypatch):
    import web.app as W
    import agents.recommendation as R
    import tools.market_data as M
    import pandas as pd
    calls = {"build": 0, "freeze": 0}
    idx = pd.date_range("2025-01-01", periods=300, freq="B")
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)
    monkeypatch.setattr(M, "fetch_price_history", lambda t, period="5y": df)
    monkeypatch.setattr(M, "fetch_fundamentals", lambda t: {})
    monkeypatch.setattr(M, "fetch_reddit_sentiment", lambda t: None)
    monkeypatch.setattr(M, "fetch_stocktwits_sentiment", lambda t: None)
    monkeypatch.setattr(M, "compute_indicators", lambda d: {})
    monkeypatch.setattr(M, "compute_signal_summary", lambda i: {})
    monkeypatch.setattr(M, "compute_algo_signals", lambda d, i: {})
    import agents.fundamentals_pit as F
    monkeypatch.setattr(F, "analyze_fundamentals_pit", lambda t, run_id=None: None)

    def build(*a, **k):
        calls["build"] += 1
        return {"ticker": "AAPL", "composite": 70.0}
    monkeypatch.setattr(R, "build_recommendation", build)
    monkeypatch.setattr(R, "log_composite_recommendation", lambda rec: (calls.__setitem__("freeze", calls["freeze"] + 1) or "rid"))
    c = W.app.test_client()
    first = c.post("/api/recommendation", json={"ticker": "AAPL"}).get_json()
    second = c.post("/api/recommendation", json={"ticker": "aapl"}).get_json()
    assert first["cache"]["hit"] is False and second["cache"]["hit"] is True
    assert second["composite"] == 70.0 and calls == {"build": 1, "freeze": 1}
    c.post("/api/recommendation", json={"ticker": "AAPL", "refresh": True})
    assert calls == {"build": 2, "freeze": 2}
