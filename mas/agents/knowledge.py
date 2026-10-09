"""Adapter for the `knowledge` sub-agent: questions no other specialist covers.

The RAG pipeline in mas/converse/knowledge.py — the local knowledge base
(this repo's docs and every earlier live answer, including the live feed's
quotes and rates) first, then FRED, quotes, Google News, SEC full-text search
and Wikipedia. Extractive and cited. The question arrives in params.
"""
from __future__ import annotations

from mas.contract import AgentRequest, AgentResult, error, ok, unavailable

AGENT_ID = "knowledge"


def available(symbol: str, asset_class: str):
    return True, ""


def run(request: AgentRequest) -> AgentResult:
    try:
        from mas.converse import knowledge
        q = (request.params or {}).get("question") or ""
        if not q:
            return unavailable(AGENT_ID, request.capability, "no question was passed")
        syms = [request.symbol] if request.symbol else []
        k = knowledge.answer(q, syms, (request.params or {}).get("shape") or "UNROUTABLE")
        if not k.get("found"):
            return unavailable(AGENT_ID, request.capability, k.get("answer") or "nothing found locally or live")
        return ok(AGENT_ID, request.capability, k, price_basis=None)
    except Exception as e:
        return error(AGENT_ID, request.capability, e)
