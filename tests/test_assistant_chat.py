"""The desk's AI Chat: team (desk + web), guardrails, endpoint — offline."""
import json

import pytest

from mas.converse import assistant, assistant_team as at, knowledge as kn, live_knowledge as lk


@pytest.fixture()
def pipe(tmp_path, monkeypatch):
    p = lk.Pipeline(lk.KnowledgeStore(str(tmp_path / "kb.db")), [])
    monkeypatch.setattr(kn, "_pipe", p)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
              "DEEPSEEK_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(assistant, "_get", lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError()))
    assistant._health.clear()
    return p


def final(q):
    return [e for e in at.run_stream(q) if e["type"] == "final"][0]["result"]


def test_the_desk_refusal_to_pick_names_stands(pipe):
    r = final("what's the best stock to buy")
    assert r["outcome"] == "REFUSED" and r["answer"].startswith("I do not pick names")


def test_orders_are_refused(pipe):
    assert final("buy 100 shares of NVDA for me")["outcome"] == "REFUSED"


def test_web_research_runs_on_its_own_shelf(pipe, monkeypatch):
    monkeypatch.setattr(lk.WebSearchFetcher, "fetch", lambda self, q, ctx: [
        lk.Doc("web", "Buybacks explained", "Companies buy back shares when they think the stock is undervalued.",
               "https://example.com/b", "web")])
    pipe.store.add([lk.Doc("wikipedia", "Share repurchase", "A share repurchase is a company buying its own shares.",
                           "https://w/b")])
    r = final("why do companies buy back shares")
    # Web and desk share one store: whichever lands first, the web finding is
    # in the answer exactly once (the orchestrator drops a repeated sentence).
    assert r["answer"].count("undervalued") == 1
    assert {t["agent"]: t["status"] for t in r["trace"]}["web"] == "OK"


def test_endpoint_streams_and_reports_no_model(pipe):
    from web.app import app
    c = app.test_client()
    r = c.post("/api/assistant/stream", json={"question": "what's the best stock to buy"})
    events = [e for e in r.get_data(as_text=True).split("\n\n") if e.startswith("event:")]
    res = json.loads(events[-1].split("data: ", 1)[1])["result"]
    assert res["outcome"] == "REFUSED" and "guardrail" in res["synthesis_skipped"]
    assert c.get("/api/assistant/status").get_json()["available"] is False
    assert c.post("/api/assistant/stream", json={"question": ""}).status_code == 400
