"""Adapter for the `live_market` sub-agent: what the stream says right now.

With a symbol: its streamed quote and day change (a one-off chart quote when
the stream does not watch it), and the streamed headlines about it.
Without one: the market pulse — indexes, VIX, the 10y/2y curve, the
watchlist's biggest movers and the market headlines.

Labelled LIVE_QUOTE: a last trade with its source and time, never a settled
close, and never an input to the desk's scores.
"""
from __future__ import annotations

from mas.contract import AgentRequest, AgentResult, error, ok, unavailable

AGENT_ID = "live_market"


def available(symbol: str, asset_class: str):
    return True, ""


def _quote(sym: str):
    from mas import live
    q = live.quote(sym)
    if q:
        return {**q, "source": "stream"}
    try:
        from mas.converse.live_feed import yahoo_quote
        q = yahoo_quote(sym)
        return {**q, "source": "one-off chart quote"} if q else None
    except Exception:
        return None


def run(request: AgentRequest) -> AgentResult:
    from mas import live
    try:
        sym = (request.symbol or "").upper()
        if sym:
            q = _quote(sym)
            if not q:
                return unavailable(AGENT_ID, request.capability, f"no live quote for {sym}")
            return ok(AGENT_ID, request.capability,
                      {"mode": "symbol", "symbol": sym, "quote": q, "headlines": live.headlines(4, about=sym)},
                      price_basis="LIVE_QUOTE")
        idx = {s: live.quote(s) for s in live.INDEXES}
        if not any(idx.values()):
            return unavailable(AGENT_ID, request.capability,
                               "no streamed market data yet" if live.enabled() else
                               "live feeds are off (LIVE_FEEDS=1 turns them on)")
        macro = {s: live.rate(s) for s in ("DGS10", "DGS2", "T10Y2Y")}
        return ok(AGENT_ID, request.capability,
                  {"mode": "pulse", "indexes": idx, "macro": macro, "movers": live.movers(),
                   "sectors": live.sectors(), "headlines": live.headlines(5)}, price_basis="LIVE_QUOTE")
    except Exception as e:
        return error(AGENT_ID, request.capability, e)
