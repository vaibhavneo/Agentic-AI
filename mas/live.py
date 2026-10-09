"""Live market data for the desk: streamed quotes, macro, headlines and movers.

One FeedHub (mas/converse/live_feed.py, shared with the other apps) per
process, started by web/app.py only when LIVE_FEEDS=1 (local/run_all.py sets
it; tests, the heartbeat and hosted copies leave it off):

    indexes     SPY QQQ DIA IWM ^VIX — every 60 s in US market hours, 30 min otherwise
    watchlist   the heartbeat universe (watchlist.txt) — every 5 min in market hours (Yahoo rate limits)
    macro       FRED: 10-year, 2-year, 10y-2y curve, fed funds, VIX close — every 6 h
    headlines   Google News: the market today, and the watchlist's biggest movers — every 20 min
    movers      a watchlist name moving 4% or more on the day becomes a "mover" event

Every event also lands in the knowledge store (data/knowledge.db) under the
knowledge fetchers' own identity (quotes, FRED), so the converse layer's
world_knowledge agent answers a price or rate question from the stream.

The desk's predictions do NOT read this. The scoring pipeline prices from
settled bars and the real-time path (mas/realtime.py) keeps its own
confirmation rules; a streamed quote here is for the conversation and the
screen, labelled with its source and time.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from mas.converse import live_feed as lf

ROOT = Path(__file__).resolve().parents[1]
INDEXES = ["SPY", "QQQ", "DIA", "IWM", "^VIX"]
MACRO = ["DGS10", "DGS2", "T10Y2Y", "DFF", "VIXCLS"]
MOVER_PCT = 4.0
_hub: Optional[lf.FeedHub] = None
_lock = threading.RLock()


def watchlist() -> List[str]:
    p = ROOT / "watchlist.txt"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        s = line.split("#", 1)[0].strip().upper()
        if s:
            out.append(s)
    return out


def movers(limit: int = 5) -> Dict[str, List[Dict[str, Any]]]:
    """Watchlist names by today's streamed change, biggest first each way."""
    rows = []
    for sym in watchlist():
        q = quote(sym)
        if q and q.get("change_pct") is not None:
            rows.append({"symbol": sym, "price": q["price"], "change_pct": q["change_pct"], "as_of": q.get("as_of")})
    rows.sort(key=lambda r: r["change_pct"])
    return {"gainers": [r for r in reversed(rows) if r["change_pct"] > 0][:limit],
            "losers": [r for r in rows if r["change_pct"] < 0][:limit], "priced": len(rows)}


_sector_cache: Dict[str, Any] = {"at": 0.0, "map": {}}


def sector_map(max_age_s: float = 3600) -> Dict[str, str]:
    """Ticker -> sector from the desk's own prediction ledger (newest call per ticker)."""
    import time as _t
    if _t.time() - _sector_cache["at"] < max_age_s and _sector_cache["map"]:
        return _sector_cache["map"]
    out: Dict[str, str] = {}
    try:
        from data import prediction_ledger as pl
        for r in pl.list_snapshots(limit=2000):
            if r.get("ticker") and r.get("sector") and r["ticker"] not in out:
                out[r["ticker"]] = r["sector"]
    except Exception:
        pass
    _sector_cache.update(at=_t.time(), map=out)
    return out


def sectors(min_names: int = 2) -> List[Dict[str, Any]]:
    """Today's average streamed move per sector across the watchlist, best first."""
    by: Dict[str, List[float]] = {}
    smap = sector_map()
    for sym in watchlist():
        q = quote(sym)
        sec = smap.get(sym)
        if q and q.get("change_pct") is not None and sec:
            by.setdefault(sec, []).append(q["change_pct"])
    rows = [{"sector": k, "avg_change_pct": round(sum(v) / len(v), 2), "names": len(v)}
            for k, v in by.items() if len(v) >= min_names]
    return sorted(rows, key=lambda r: -r["avg_change_pct"])


def _mover_events() -> List[lf.Event]:
    out = []
    for side in movers(limit=10).values():
        if not isinstance(side, list):
            continue
        for r in side:
            if abs(r["change_pct"]) >= MOVER_PCT:
                out.append(lf.Event("movers", "mover", f"mover:{r['symbol']}", r,
                                    f"{r['symbol']} is {r['change_pct']:+.2f}% on the day at ${r['price']:,.2f}.",
                                    source="streamed quotes", ttl_s=1800))
    return out


def _headline_queries() -> List[str]:
    m = movers(limit=3)
    return ["stock market today"] + [f"{r['symbol']} stock" for r in m["gainers"][:2] + m["losers"][:2]]


def hub() -> lf.FeedHub:
    global _hub
    with _lock:
        if _hub is None:
            from mas.converse.knowledge import pipeline
            _hub = lf.FeedHub([
                lf.QuoteFeed(lambda: INDEXES, name="indexes", interval_s=60, closed_interval_s=1800),
                lf.QuoteFeed(watchlist, name="watchlist", interval_s=300, closed_interval_s=1800, max_symbols=120),
                lf.FredFeed(MACRO, name="macro"),
                lf.HeadlineFeed(_headline_queries, name="headlines", per_query=4),
                lf.FnFeed("movers", _mover_events, interval_s=300, closed_interval_s=1800),
            ], store=pipeline().store, db_path=str(ROOT / "data" / "live_events.db"))
            _hub.feeds["headlines"].interval_s = 1200
        return _hub


def enabled() -> bool:
    return os.environ.get("LIVE_FEEDS") == "1"


def start_if_enabled() -> bool:
    if enabled():
        hub().start()
        return True
    return False


def ensure_fresh(symbols) -> List[str]:
    """Read-through: in market hours, re-quote now whatever a question needs
    that is older than 60 s. Closed market: the last close stands."""
    if _hub is None or not lf.us_market_open():
        return []
    try:
        return _hub.refresh("indexes", list(symbols), 60.0)
    except Exception:
        return []


def quote(sym: str) -> Optional[Dict[str, Any]]:
    return _hub.latest_value(f"quote:{sym.upper()}") if _hub is not None else None


def rate(series: str) -> Optional[Dict[str, Any]]:
    return _hub.latest_value(f"rate:{series}") if _hub is not None else None


def headlines(limit: int = 6, about: Optional[str] = None) -> List[Dict[str, Any]]:
    if _hub is None:
        return []
    evs = sorted(_hub.by_kind("headline"), key=lambda e: -e.ts)
    if about:
        evs = [e for e in evs if (e.value.get("query") or "").split(" ")[0] == about.upper()]
    return [{"title": e.value["title"], "url": e.url, "query": e.value.get("query"), "at": e.to_dict()["at"]}
            for e in evs[:limit]]


def snapshot() -> Dict[str, Any]:
    if _hub is None:
        return {"enabled": enabled(), "running": False, "feeds": {}, "latest": []}
    return {"enabled": True, **_hub.snapshot()}
