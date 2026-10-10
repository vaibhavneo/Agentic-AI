"""Quant Lab endpoints (web/quant_api.py) and the live scanner (quant/live.py), offline."""
import pandas as pd
import pytest
from flask import Flask

from quant import intraday as I
from quant import live as QL
from quant import prices as P
from tests.test_quant_intraday import _breakout_day, _day, _flat_days
from tests.test_quant_portfolio import market  # noqa: F401  (fixture)
from web.quant_api import bp


@pytest.fixture()
def client(market, monkeypatch):  # noqa: F811
    http, _ = market
    monkeypatch.setattr(P, "_get", lambda url, timeout=12.0: http(url))
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client()


H = [{"symbol": "AAA", "shares": 10}, {"symbol": "BBB", "shares": 10}, {"symbol": "CCC", "value": 2000}]


def test_risk_optimize_and_project_answer(client):
    r = client.post("/api/quant/risk", json={"holdings": H, "years": 3}).get_json()
    assert {h["symbol"] for h in r["holdings"]} == {"AAA", "BBB", "CCC"} and r["portfolio"]["vol_ann"] > 0
    o = client.post("/api/quant/optimize", json={"holdings": H, "method": "all"}).get_json()
    assert set(o) == {"min_variance", "max_sharpe", "risk_parity"}
    rb = o["min_variance"]["rebalance"]
    assert abs(sum(rb["current_weights"].values()) - 1) < 1e-3 and rb["trades"]
    p = client.post("/api/quant/project", json={"holdings": H, "years": 5, "monthly_contribution": 100,
                                                "goal": 5000}).get_json()
    assert p["years"] == 5 and "prob_goal" in p and p["drift"] == "conservative"


@pytest.mark.parametrize("url,body,msg", [
    ("/api/quant/risk", {"holdings": [{"symbol": "NV DA", "shares": 1}]}, "not a symbol"),
    ("/api/quant/risk", {"holdings": [{"symbol": "AAA", "shares": -5}]}, "positive"),
    ("/api/quant/risk", {"holdings": []}, "non-empty"),
    ("/api/quant/optimize", {"symbols": ["AAA"]}, "at least two"),
    ("/api/quant/optimize", {"symbols": ["AAA", "BBB"], "method": "yolo"}, "method must be"),
    ("/api/quant/project", {"holdings": H, "years": 99}, "between 1 and 40"),
    ("/api/quant/project", {"holdings": H, "drift": "moon"}, "drift must be"),
])
def test_bad_requests_are_400_with_a_reason(client, url, body, msg):
    r = client.post(url, json=body)
    assert r.status_code == 400 and msg in r.get_json()["error"]


def test_the_page_is_served(client):
    r = client.get("/quant")
    assert r.status_code == 200 and b"Quant Lab" in r.data and b"never orders" in r.data


@pytest.fixture()
def live_bars(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CACHE", tmp_path)
    monkeypatch.setattr(QL, "_journal", I.Journal(tmp_path / "j.db"))
    history, _ = _flat_days(8)
    day = _breakout_day(pd.Timestamp("2026-09-15").date())
    state = {"bars": pd.concat(history + [day])}
    monkeypatch.setattr(P, "intraday", lambda s, days=60, http=None: state["bars"])
    return state, history, day


def test_a_fresh_signal_is_journaled_and_published_once(live_bars):
    state, history, day = live_bars
    now = pd.Timestamp("2026-09-15 10:25", tz="America/New_York")
    evs = QL.signal_events(["TEST"], now=now)
    sig = [e for e in evs if e.kind == "signal" and e.value["rule"] == "orb_long"]
    assert len(sig) == 1 and "not an order" in sig[0].text and sig[0].value["rule_record"]["n"] >= 1
    assert "entry $101.00, stop $99.75, 2R target $103.50" in sig[0].text
    assert not [e for e in QL.signal_events(["TEST"], now=now) if e.kind == "signal"]      # deduped


def test_a_stale_or_forming_signal_is_not_published(live_bars):
    state, *_ = live_bars
    late = pd.Timestamp("2026-09-15 14:00", tz="America/New_York")                        # 3 h old
    assert not [e for e in QL.signal_events(["TEST"], now=late) if e.value.get("rule") == "orb_long"]
    forming = pd.Timestamp("2026-09-15 10:12", tz="America/New_York")                     # 10:10 bar not closed
    assert "orb_long" not in {s["rule"] for s in QL.scan_all(["TEST"], now=forming)["signals"]}


def test_an_open_paper_trade_settles_into_a_close_event(live_bars):
    state, history, day = live_bars
    QL.signal_events(["TEST"], now=pd.Timestamp("2026-09-15 10:25", tz="America/New_York"))
    state["bars"] = pd.concat(history + [day, _day(pd.Timestamp("2026-09-16").date(), [102.0] * 78)])
    closes = [e for e in QL.signal_events(["TEST"], now=pd.Timestamp("2026-09-16 10:00", tz="America/New_York"))
              if e.kind == "signal_close"]
    assert any(e.value["rule"] == "orb_long" and e.value["r"] == pytest.approx(0.8) for e in closes)
    assert QL.journal_summary()["stats"]["orb_long"]["n"] == 1
