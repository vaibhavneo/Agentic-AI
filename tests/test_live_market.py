"""The desk's live feed (mas/live.py) and the two registered agents it backs —
live_market and knowledge — offline: a FeedHub fed by the test."""
import pytest

from mas import live, registry
from mas.contract import AgentRequest
from mas.converse import live_feed as lf


@pytest.fixture()
def hub(monkeypatch):
    h = lf.FeedHub([])
    monkeypatch.setattr(live, "_hub", h)
    monkeypatch.setattr(live, "watchlist", lambda: ["AAA", "BBB", "CCC"])
    return h


def q(h, sym, price, chg):
    h.publish(lf.Event("t", "quote", f"quote:{sym}", {"symbol": sym, "price": price, "change_pct": chg,
                                                      "as_of": "2026-10-09T13:00"}))


def test_both_agents_are_registered_and_need_no_symbol():
    registry.load.cache_clear()
    assert {"live_market", "world_knowledge"} <= set(registry.CAPABILITIES)
    assert [a["id"] for a in registry.agents("live_market", have_symbol=False)] == ["live_market"]
    assert [a["id"] for a in registry.agents("world_knowledge", have_symbol=False)] == ["knowledge"]
    for aid in ("live_market", "knowledge"):
        assert registry.get(aid)["writes"] == {}


def test_movers_rank_both_ways(hub):
    q(hub, "AAA", 10.0, 5.0)
    q(hub, "BBB", 20.0, -6.0)
    q(hub, "CCC", 30.0, 1.0)
    m = live.movers()
    assert [r["symbol"] for r in m["gainers"]] == ["AAA", "CCC"] and [r["symbol"] for r in m["losers"]] == ["BBB"]
    evs = live._mover_events()
    assert sorted(e.key for e in evs) == ["mover:AAA", "mover:BBB"]          # >= 4% either way


def test_watchlist_file_parsing(tmp_path, monkeypatch):
    p = tmp_path / "watchlist.txt"
    p.write_text("# comment\nAAPL\n\nmsft  # inline\n")
    monkeypatch.setattr(live, "ROOT", tmp_path)
    assert live.watchlist() == ["AAPL", "MSFT"]


def test_live_market_pulse(hub):
    from mas.agents import live_market
    q(hub, "SPY", 778.57, 0.6)
    q(hub, "AAA", 10.0, 5.0)
    r = live_market.run(AgentRequest("", "UNKNOWN", "live_market"))
    assert r.status == "OK" and r.data["mode"] == "pulse" and r.price_basis == "LIVE_QUOTE"
    assert r.data["indexes"]["SPY"]["price"] == 778.57 and r.data["movers"]["gainers"][0]["symbol"] == "AAA"


def test_live_market_symbol_falls_back_to_a_one_off_quote(hub, monkeypatch):
    from mas.agents import live_market
    monkeypatch.setattr("mas.converse.live_feed.yahoo_quote", lambda s: {"symbol": s, "price": 5.0, "change_pct": 1.0})
    r = live_market.run(AgentRequest("ZZZ", "EQUITY", "live_market"))
    assert r.status == "OK" and r.data["quote"]["source"] == "one-off chart quote"


def test_live_market_declines_with_no_data(monkeypatch):
    from mas.agents import live_market
    monkeypatch.setattr(live, "_hub", None)
    monkeypatch.delenv("LIVE_FEEDS", raising=False)
    r = live_market.run(AgentRequest("", "UNKNOWN", "live_market"))
    assert r.status == "UNAVAILABLE" and "LIVE_FEEDS" in r.reason


def test_knowledge_agent_needs_a_question():
    from mas.agents import knowledge
    r = knowledge.run(AgentRequest("", "UNKNOWN", "world_knowledge", {}))
    assert r.status == "UNAVAILABLE" and "no question" in r.reason


def test_pulse_composer():
    from mas.converse.reply import COMPOSERS
    lines = COMPOSERS["live_market"]({"mode": "pulse", "indexes": {"SPY": {"price": 1.0, "change_pct": 0.5,
                                                                            "as_of": "t"}, "^VIX": {"price": 15.0}},
                                      "macro": {"DGS10": {"value": 5.22, "date": "2026-10-08"}},
                                      "movers": {"gainers": [{"symbol": "AAA", "change_pct": 5.0}], "losers": [],
                                                 "priced": 1}, "headlines": [{"title": "Stocks rise"}]}, "")
    text = " ".join(lines)
    assert "S&P 500 $1.00 (+0.50%)" in text and "VIX 15.00" in text and "10-year 5.22%" in text
    assert "up AAA +5.00%" in text and "- Stocks rise" in text


def test_endpoints(monkeypatch):
    monkeypatch.delenv("LIVE_FEEDS", raising=False)
    from web.app import app
    c = app.test_client()
    assert c.get("/api/live").get_json()["enabled"] is False
    assert c.get("/api/live/stream").status_code == 503


def test_sector_heat(hub, monkeypatch):
    monkeypatch.setattr(live, "sector_map", lambda max_age_s=3600: {"AAA": "Tech", "BBB": "Tech", "CCC": "Energy"})
    q(hub, "AAA", 10.0, 2.0)
    q(hub, "BBB", 10.0, 4.0)
    q(hub, "CCC", 10.0, -1.0)
    assert live.sectors() == [{"sector": "Tech", "avg_change_pct": 3.0, "names": 2}]       # Energy has one name
    assert [r["sector"] for r in live.sectors(min_names=1)] == ["Tech", "Energy"]


def test_pulse_composer_shows_sectors():
    from mas.converse.reply import COMPOSERS
    lines = COMPOSERS["live_market"]({"mode": "pulse", "indexes": {}, "macro": {}, "movers": {},
                                      "sectors": [{"sector": "Tech", "avg_change_pct": 3.0, "names": 4},
                                                  {"sector": "Utilities", "avg_change_pct": 0.5, "names": 3},
                                                  {"sector": "Energy", "avg_change_pct": -1.5, "names": 5}]}, "")
    assert "best Tech +3.00% (4), Utilities +0.50% (3); worst Energy -1.50% (5), Utilities +0.50% (3)" in " ".join(lines)
