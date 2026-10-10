"""Quant Lab specialists in the desk's AI Chat (mas/converse/quant_agents.py) — offline."""
import json

import pytest

from mas.converse import agent_core as ac
from mas.converse import assistant, assistant_team as at, quant_agents as QA
from quant import live as QL
from quant import prices as P
from tests.test_quant_portfolio import market  # noqa: F401  (fixture)


@pytest.mark.parametrize("q,signals,personal", [
    ("Any intraday setups?", True, False),
    ("VWAP setups on TSLA", True, False),
    ("What is VWAP?", False, False),
    ("how does an opening range breakout work", False, False),
    ("How risky is my portfolio?", False, True),
    ("Should I buy NVDA?", False, False),
])
def test_routing(q, signals, personal):
    assert QA.wants_signals(q) is signals and QA.is_personal(q) is personal
    assert "VWAP" not in QA.named_symbols(q)


def test_projection_reads_years_contributions_and_goal():
    assert QA._projection_params("worth in 15 years with $1,200 a month, goal of $1.5m") == \
        {"years": 15, "monthly_contribution": 1200.0, "goal": 1_500_000.0}
    assert QA._projection_params("reach 250k in 20 yrs with 2k per month") == \
        {"years": 20, "monthly_contribution": 2000.0, "goal": 250_000.0}


def test_holdings_are_validated():
    rows = QA.holdings_from({"holdings": [{"symbol": "nvda", "shares": "4"}, {"ticker": "AAPL", "value": 900},
                                          {"symbol": "DROP TABLE", "shares": 1}, {"symbol": "X", "shares": -3}, "junk"]})
    assert rows == [{"symbol": "NVDA", "shares": 4.0}, {"symbol": "AAPL", "value": 900.0}]


def _task(q, holdings=None):
    return ac.Task(question=q, ctx={"holdings": holdings} if holdings else {})


def test_portfolio_risk_answer_is_cited_and_matches_the_model(market, monkeypatch):  # noqa: F811
    http, _ = market
    monkeypatch.setattr(P, "_get", lambda url, timeout=12.0: http(url))
    H = [{"symbol": "AAA", "shares": 10}, {"symbol": "BBB", "shares": 10}, {"symbol": "CCC", "shares": 10}]
    agent = QA.QuantPortfolioAgent()
    assert agent.bid(_task("how risky is my portfolio", H)) > 0.5 and agent.bid(_task("is NVDA risky")) == 0
    f = agent.run(_task("how risky is my portfolio", H), None)
    from quant import portfolio as Q
    r = Q.risk(H)
    assert f"{r['portfolio']['vol_ann'] * 100:.1f}% annual volatility" in f.lines[0]
    assert all(ln.endswith("[1].") for ln in f.lines) and f.sources[0]["url"] == "/quant"
    both = agent.run(_task("optimize my portfolio and project it 5 years", H), None)
    assert any("Risk parity would hold" in ln for ln in both.lines) and any("Over 5 years" in ln for ln in both.lines)
    assert any("in-sample" in ln for ln in both.lines) and len(both.sources) == 2


def test_no_holdings_says_how_to_add_them():
    f = QA.QuantPortfolioAgent().run(_task("how risky is my portfolio"), None)
    assert f.ok and "Quant Lab" in f.lines[0] and not f.sources


SCAN = {"as_of": "2026-10-09 15:55:00-04:00", "symbols": ["NVDA", "TSLA"], "missing": [], "backtest_trades": 40,
        "signals": [{"symbol": "TSLA", "rule": "vwap_reclaim", "side": "long", "label": QL.LABEL["vwap_reclaim"],
                     "ts": "2026-10-09 12:00:00-04:00", "entry": 383.88, "stop": 379.71, "target": 392.21,
                     "rvol": 1.8, "age_min": 5, "rule_record": None}],
        "backtest": {"vwap_reclaim": {"n": 30, "win_rate": 0.4, "avg_r": -0.05, "target_rate": 0.1, "total_r": -1.5,
                                      "t_stat": -0.4},
                     "gap_and_go": {"n": 20, "win_rate": 0.55, "avg_r": 0.44, "target_rate": 0.2, "total_r": 8.8,
                                    "t_stat": 2.3}}}


def test_signals_answer_states_each_rules_record(monkeypatch):
    monkeypatch.setattr(QL, "scan_all", lambda syms=None, **k: SCAN)
    f = QA.QuantSignalsAgent().run(_task("any VWAP setups?"), None)
    text = "\n".join(f.lines)
    assert "TSLA VWAP reclaim (long) at 12:00 ET: entry $383.88, stop $379.71, 2R target $392.21" in text
    assert "measured edge over the last ~60 sessions: gap-and-go (long) +0.44R over 20 trades" in text
    assert "nothing here places an order" in text


def test_the_scanner_takes_setup_questions_from_the_desk_and_web():
    task = _task("Any intraday setups?")
    assert at.DeskAgent().bid(task) == 0 and QA.QuantSignalsAgent().bid(task) > 0.5
    assert "quant_signals" in at.WebResearchAgent.yields_to
    assert at.DeskAgent().bid(_task("VWAP setups on TSLA")) > 0.5       # a named stock still gets the desk's read


def test_endpoint_keeps_a_personal_portfolio_answer_on_a_local_model(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
              "DEEPSEEK_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(assistant, "_get", lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError()))
    called = []
    monkeypatch.setattr(assistant, "_post", lambda *a, **k: called.append(a[0]) or {"content": [{"type": "text", "text": "x"}]})
    seen = {}

    def fake_stream(q, sid=None, holdings=None):
        seen["holdings"] = holdings
        yield {"type": "final", "result": {"outcome": "ANSWERED", "answer": "Your portfolio has run at 20.2% [1]."}}
    monkeypatch.setattr(at, "run_stream", fake_stream)
    from web.app import app
    c = app.test_client()
    body = c.post("/api/assistant/stream", json={"question": "how risky is my portfolio",
                                                 "holdings": [{"symbol": "NVDA", "shares": 3}]}).get_data(as_text=True)
    res = json.loads([e for e in body.split("\n\n") if e.startswith("event:")][-1].split("data: ", 1)[1])["result"]
    assert seen["holdings"] == [{"symbol": "NVDA", "shares": 3}]
    assert called == [] and "local model" in res["synthesis_skipped"]
