"""The desk-views feed: the canonical ledger's calls reach the hosted desk."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def ledger(monkeypatch):
    from data import ledger as dl, store
    from data import prediction_ledger as pl
    from data import desk_views as V
    tmp = Path(tempfile.mkdtemp())
    prev = (store.DB_PATH, getattr(store, "_DB_PATH", None), pl._db_override, dl._db_override)
    store._DB_PATH = store.DB_PATH = tmp / "s.db"
    pl.set_db_path(tmp / "s.db")
    dl.set_db_path(tmp / "l.db")
    monkeypatch.delenv("LEDGER_ROLE", raising=False)
    V.clear_cache()
    yield pl
    store.DB_PATH, store._DB_PATH = prev[0], prev[1]
    pl.set_db_path(prev[2])
    dl.set_db_path(prev[3])
    V.clear_cache()


def _call(pl, ticker, day, action="BUY"):
    return pl.freeze_prediction({"ticker": ticker, "generated_at": f"{day}T00:00:00", "current_price": 100.0,
                                 "action": action, "sector": "Tech", "regime": "LOW",
                                 "confidence": {"statistical_edge": {"level": "LOW", "score": 0.3}},
                                 "pillars": {}, "claims": {}})


def test_views_are_the_latest_live_call_per_ticker(ledger):
    from datetime import date, timedelta
    from data.desk_views import build_views
    today, old = date.today().isoformat(), (date.today() - timedelta(days=3)).isoformat()
    _call(ledger, "MSFT", old, "SELL")
    _call(ledger, "MSFT", today, "BUY")
    _call(ledger, "AAPL", today)
    _call(ledger, "TEST", today)                                    # synthetic: quarantined
    _call(ledger, "KO", (date.today() - timedelta(days=40)).isoformat())   # too old
    v = build_views()
    assert [r["ticker"] for r in v["views"]] == ["AAPL", "MSFT"]
    msft = next(r for r in v["views"] if r["ticker"] == "MSFT")
    assert msft["action"] == "BUY" and msft["source"] == "heartbeat-feed"
    assert msft["confidence"]["statistical_edge"] == "LOW"


def test_merge_adds_only_newer_calls_and_drops_nothing():
    from data.desk_views import merge
    local = [{"ticker": "MSFT", "created_at": "2026-10-05T10:00:00", "action": "HOLD"},
             {"ticker": "KO", "created_at": "2026-10-01T09:00:00", "action": "BUY"}]
    feed = [{"ticker": "MSFT", "created_at": "2026-10-04T00:00:00", "action": "SELL"},   # older: ignored
            {"ticker": "KO", "created_at": "2026-10-06T00:00:00", "action": "REDUCE"},   # newer: added
            {"ticker": "NFLX", "created_at": "2026-10-06T00:00:00", "action": "BUY"}]    # new name: added
    out = merge(local, feed)
    assert [(r["ticker"], r["action"]) for r in out] == [
        ("KO", "REDUCE"), ("NFLX", "BUY"), ("MSFT", "HOLD"), ("KO", "BUY")]


def test_merge_respects_a_ticker_filter():
    from data.desk_views import merge
    out = merge([], [{"ticker": "NFLX", "created_at": "2026-10-06"}, {"ticker": "KO", "created_at": "2026-10-06"}],
                ticker="NFLX")
    assert [r["ticker"] for r in out] == ["NFLX"]


def test_fetch_degrades_cleanly_and_caches():
    from data import desk_views as V
    V.clear_cache()
    assert V.fetch(repo="")["reason"] == "DESK_VIEWS_REPO not set"
    calls = []

    def boom(r, t):
        calls.append(1)
        raise ConnectionError("down")
    out = V.fetch(repo="me/x", token="t", download=boom)
    assert out["available"] is False and "ConnectionError" in out["reason"]
    good = json.dumps({"generated_at": "2026-10-08T00:00:00", "views": [{"ticker": "V"}]})
    V.clear_cache()
    first = V.fetch(repo="me/x", token="t", download=lambda r, t: (calls.append(2) or good))
    again = V.fetch(repo="me/x", token="t", download=lambda r, t: (calls.append(3) or good))
    assert first["available"] and again["views"] == [{"ticker": "V"}]
    assert 3 not in calls                                          # served from the 15-minute cache


def test_only_the_canonical_ledger_publishes(ledger, monkeypatch):
    from data.desk_views import publish

    class Hub:
        def __init__(self):
            self.files = {}

        def create_repo(self, *a, **k):
            pass

        def upload_file(self, path_or_fileobj, path_in_repo, **k):
            self.files[path_in_repo] = json.loads(path_or_fileobj)
    from datetime import date
    _call(ledger, "MSFT", date.today().isoformat())
    hub = Hub()
    assert publish("me/x", api=hub)["published"] == 1
    assert hub.files["views/latest.json"]["views"][0]["ticker"] == "MSFT"
    monkeypatch.setenv("LEDGER_ROLE", "secondary")
    assert publish("me/x", api=Hub())["skipped"] == "secondary ledger"


def test_the_predictions_endpoint_merges_the_feed(ledger, monkeypatch):
    from data import desk_views as V
    monkeypatch.setattr(V, "fetch", lambda *a, **k: {"available": True, "generated_at": "2026-10-08",
                                                     "reason": None,
                                                     "views": [{"ticker": "NFLX", "created_at": "2026-10-08T00:00:00",
                                                                "action": "BUY", "source": "heartbeat-feed"}]})
    from web.app import app
    r = app.test_client().get("/api/predictions").get_json()
    assert r["feed"]["available"] and r["feed"]["count"] == 1
    assert any(p["ticker"] == "NFLX" and p["source"] == "heartbeat-feed" for p in r["predictions"])
