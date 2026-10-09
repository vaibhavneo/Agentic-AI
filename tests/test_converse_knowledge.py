"""The knowledge fallback in the converse engine — fully offline (stub fetchers).

What must hold:
  - parse() is untouched, and shape() reads only parse() + regexes (no network);
  - the no-pick refusal ("what's the best stock to buy") is never overridden;
  - a news question about a named symbol is answered by headlines + a quote,
    without a research run it did not ask for;
  - when the knowledge layer finds nothing, or fails, the old reply stands.
"""
from __future__ import annotations

import socket

import pytest

from mas.converse import engine, knowledge as kn, live_knowledge as lk, turn
from mas.converse.intent import parse


class Stub(lk.Fetcher):
    def __init__(self, name, docs, kinds=("reference",), applies=True, ids=None):
        self.name, self.docs, self.kinds, self._applies, self.ids, self.calls = name, docs, kinds, applies, ids, 0

    def applies(self, q, ctx):
        return self._applies if not callable(self._applies) else self._applies(q, ctx)

    def fetch(self, q, ctx):
        self.calls += 1
        return self.docs

    def cache_ids(self, q, ctx):
        return self.ids or []


@pytest.fixture()
def pipe(tmp_path, monkeypatch):
    p = lk.Pipeline(lk.KnowledgeStore(str(tmp_path / "kb.db")), [])
    monkeypatch.setattr(kn, "_pipe", p)
    return p


@pytest.mark.parametrize("q,want", [
    ("latest news on NVDA", "NEWS"),
    ("why is TSLA down today", "NEWS"),
    ("what is the 10-year yield", "UNROUTABLE"),
    ("what's happening in the market today", "UNROUTABLE"),
    ("what is a covered call", "CONCEPT"),
    ("what's the best stock to buy", None),
    ("tell me what to do with my money", None),
    ("asdfgh", None),
    ("NVDA", None),
    ("should I add to NVDA", None),
])
def test_shape(q, want):
    assert kn.shape(q, parse(q)) == want


def test_shape_does_no_network_io(monkeypatch):
    class Boom(socket.socket):
        def __init__(self, *a, **k):
            raise AssertionError("shape() opened a socket")
    monkeypatch.setattr(socket, "socket", Boom)
    for q in ("latest news on NVDA", "what is the 10-year yield", "what is a covered call", "asdfgh"):
        kn.shape(q, parse(q))


def test_unroutable_question_gets_a_cited_live_answer(pipe):
    fred = Stub("fred", [lk.Doc("fred", "10-year Treasury yield (DGS10)", "The 10-year Treasury yield was 5.28% on "
                                "2026-10-07.", "https://fred.stlouisfed.org/series/DGS10", kind="fact")],
                kinds=("fact",))
    pipe.fetchers = [fred]
    out = turn("what is the 10-year yield")
    r = out["reply"]
    assert r["kind"] == "KNOWLEDGE" and "5.28%" in r["blocks"][0]["lines"][0]
    assert r["blocks"][0]["sources"][0]["source"] == "fred" and out["knowledge"]["shape"] == "UNROUTABLE"


def test_concept_answer_keeps_the_which_symbol_question(pipe):
    pipe.fetchers = [Stub("wikipedia", [lk.Doc("wikipedia", "Covered option", "A covered call sells a call option "
                                               "against shares you own.")])]
    r = turn("what is a covered call")["reply"]
    assert "covered call sells" in r["blocks"][0]["lines"][0]
    assert any("Which symbol?" in " ".join(b["lines"]) for b in r["blocks"][1:])


def test_no_pick_refusal_is_never_overridden(pipe):
    w = Stub("wikipedia", [lk.Doc("wikipedia", "Best stock", "The best stock to buy is ACME.")])
    pipe.fetchers = [w]
    r = turn("what's the best stock to buy")["reply"]
    assert r["kind"] == "NEEDS_SUBJECT" and w.calls == 0 and "ACME" not in str(r)


def _only_knowledge_specialists(monkeypatch):
    real = engine._run_capability

    def guard(cap, *a, **k):
        if cap not in ("world_knowledge", "live_market"):
            raise AssertionError(f"{cap} ran for a news question")
        return real(cap, *a, **k)
    monkeypatch.setattr(engine, "_run_capability", guard)


def test_news_on_a_bare_symbol_skips_the_research_run(pipe, monkeypatch):
    """The live_market agent states the price; the knowledge agent finds the
    why — and nothing else on the roster runs."""
    _only_knowledge_specialists(monkeypatch)
    monkeypatch.setattr("mas.agents.live_market._quote", lambda s: {"price": 230.48, "change_pct": -2.94,
                                                                    "as_of": "2026-10-09T13:00", "source": "stream"})
    news = Stub("news", [lk.Doc("news", "Nvidia slides on OpenAI report", "Nvidia slides on OpenAI report. "
                                "Related: NVDA.", "n1", kind="news")], kinds=("news",))
    quote = Stub("quote", [], kinds=("fact",), applies=lambda q_, ctx: bool(ctx.get("tickers")))
    pipe.fetchers = [quote, news]
    out = turn("latest news on NVDA")
    r = out["reply"]
    assert r["kind"] == "KNOWLEDGE" and [b["capability"] for b in r["blocks"]] == ["live_market", "live_knowledge"]
    assert "$230.48" in r["blocks"][0]["lines"][0] and "-2.94%" in r["blocks"][0]["lines"][0]
    assert "OpenAI report" in " ".join(r["blocks"][1]["lines"])
    assert quote.calls == 0                                              # the price is not fetched twice
    assert {t["capability"] for t in out["trace"]} >= {"live_market", "world_knowledge"}


def test_pulse_question_gets_the_streamed_market(pipe, monkeypatch):
    from mas import live
    from mas.converse import live_feed as lf
    hub = lf.FeedHub([])
    monkeypatch.setattr(live, "_hub", hub)
    monkeypatch.setattr(live, "watchlist", lambda: ["AAA", "BBB"])
    for sym, p, c in (("SPY", 778.57, 0.6), ("^VIX", 14.84, -3.7), ("AAA", 10.5, 5.0), ("BBB", 9.0, -2.0)):
        hub.publish(lf.Event("t", "quote", f"quote:{sym}", {"symbol": sym, "price": p, "change_pct": c,
                                                            "as_of": "2026-10-09T13:00"}))
    out = turn("what's moving today")
    r = out["reply"]
    text = " ".join(r["blocks"][0]["lines"])
    assert r["blocks"][0]["capability"] == "live_market" and "S&P 500 $778.57 (+0.60%)" in text
    assert "VIX 14.84" in text and "up AAA +5.00%" in text and "down BBB -2.00%" in text


def test_pulse_shape():
    assert kn.shape("what's moving today", parse("what's moving today")) == "PULSE"
    assert kn.shape("how's the market right now", parse("how's the market right now")) == "PULSE"
    assert kn.shape("what's the best stock to buy", parse("what's the best stock to buy")) is None


def test_nothing_found_keeps_the_original_reply(pipe):
    pipe.fetchers = [Stub("wikipedia", [])]
    r = turn("what is the zorblax coefficient of the quux")["reply"]
    assert r["kind"] == "UNROUTABLE" and "could not tell" in r["blocks"][0]["lines"][0]


def test_a_failing_knowledge_layer_never_sinks_the_turn(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kb locked")
    monkeypatch.setattr(kn, "answer", boom)
    out = turn("what is the 10-year yield")
    assert out["reply"]["kind"] == "UNROUTABLE" and "kb locked" in out["knowledge"]["error"]


def test_news_question_with_nothing_found_says_so(pipe, monkeypatch):
    _only_knowledge_specialists(monkeypatch)
    monkeypatch.setattr("mas.agents.live_market._quote", lambda s: None)
    pipe.fetchers = [Stub("news", [], kinds=("news",))]
    r = turn("latest news on NVDA")["reply"]
    assert r["kind"] == "EMPTY" and r["blocks"][0]["lines"][0]
