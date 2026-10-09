"""Questions the specialists don't cover — answered locally first, live when not.

The router (intent.py) is deterministic and graded on a frozen corpus, and it
stays that way: this module never changes what parse() returns. It is the
engine's fallback for three shapes the specialists cannot answer:

    UNROUTABLE      "what's the 10-year yield?", "what's happening in the
                    market today?" — no specialist exists for it, so the turn
                    used to end in "I could not tell what you want".
    CONCEPT         "what is a covered call?" — options needs a symbol, so the
                    turn asked "which symbol?". Now it explains the concept and
                    still asks for a symbol to price one.
    NEWS            "latest news on NVDA", "why is TSLA down today?" — a named
                    symbol with a news-shaped question. The headlines and the
                    live quote answer it; a full research run would not.

Sources (mas/converse/live_knowledge.py, shared with the other apps): a local
SQLite FTS5 knowledge base (data/knowledge.db — this repo's docs plus every
earlier live answer still within its time-to-live), then live FRED, the desk's
own yfinance real-time quote, Google News RSS, SEC EDGAR full-text search
(only with SEC_USER_AGENT set) and Wikipedia. Extractive and cited: nothing is
generated, so nothing can be invented — the same rule as every specialist.

"What should I buy?" is NOT a knowledge question. The no-pick refusal in
intent.py runs first and this module never overrides it.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import live_knowledge as lk

ROOT = Path(__file__).resolve().parents[2]
KB_PATH = Path(os.environ.get("KNOWLEDGE_DB") or ROOT / "data" / "knowledge.db")
LOCAL_DOCS = ["README.md", "docs/EVALUATION.md"]

NEWS = re.compile(r"\b(news|headlines?|what happened|happening|why (is|are|did|was)\b.*\b(down|up|fall\w*|drop\w*|"
                  r"ris\w*|jump\w*|sink\w*|surg\w*|plung\w*|soar\w*|moving|rally\w*|crash\w*)|announce\w*)\b", re.I)
CONCEPT = re.compile(r"^\s*(what('s| is| are| does)|who (is|was)|define|explain|how does)\b", re.I)

_pipe: Optional[lk.Pipeline] = None
_lock = threading.Lock()


def _sec_ua() -> str:
    try:
        from financial_data.providers.edgar import _load_user_agent
        return _load_user_agent()
    except Exception:
        return ""


def _quote(sym: str) -> Optional[Dict[str, Any]]:
    from financial_data.providers.yfinance_realtime import _quote_one
    try:
        d = _quote_one(sym, 0.9)
    except Exception:
        return None
    ex = d.get("extra") or {}
    return {"price": d["value"], "change_pct": ex.get("change_pct"), "as_of": d.get("retrieved_at", "")[:16].replace("T", " "),
            "source": "yfinance real-time", "url": f"https://finance.yahoo.com/quote/{sym}"}


def _news_query(question: str, ctx: Dict[str, Any]) -> str:
    if ctx.get("tickers"):
        return f"{ctx['tickers'][0]} stock"
    if re.search(r"\bmarkets?\b", question, re.I) and not re.search(r"\b(housing|real estate|job|labor)\b", question, re.I):
        return "stock market today"
    q = " ".join(lk.terms(question))
    return q if re.search(r"\b(stock|shares|index|dow|nasdaq|s&p)\b", q) else f"{q} stock market"


def pipeline() -> lk.Pipeline:
    global _pipe
    with _lock:
        if _pipe is None:
            store = lk.KnowledgeStore(str(KB_PATH))
            docs = []
            for rel in LOCAL_DOCS:
                p = ROOT / rel
                if p.exists():
                    for i, part in enumerate(re.split(r"\n(?=#{1,3} )", p.read_text(errors="ignore"))):
                        if part.strip():
                            head = part.strip().splitlines()[0].lstrip("# ").strip()
                            docs.append(lk.Doc("local:docs", f"{rel} — {head}", " ".join(re.sub(r"[#`*|]", " ", part).split()),
                                               f"{rel}#{i}", "appdoc", ttl_s=10 * 365 * 86400))
            store.add(docs)
            _pipe = lk.Pipeline(store, [
                lk.FredFetcher(lk.MARKET_SERIES),
                lk.QuoteFetcher(_quote),
                lk.GoogleNewsFetcher(query_fn=_news_query),
                lk.SecFullTextFetcher(_sec_ua()),
                lk.WikipediaFetcher(),
            ])
        return _pipe


PULSE = re.compile(r"\b(what'?s moving|top movers|market movers|biggest movers|movers today|how'?s the market (now|today|"
                   r"right now|doing)|market (right )?now|stocks? (today|right now))\b", re.I)
LIVE = re.compile(r"\b(now|today|right now|live|currently|so far|this morning|this afternoon)\b", re.I)


def shape(text: str, parsed: Dict[str, Any]) -> Optional[str]:
    """Which fallback (if any) this turn gets: UNROUTABLE, CONCEPT, NEWS,
    PULSE (the streamed market: indexes, curve, movers, headlines) or None."""
    kind = parsed.get("kind")
    caps = parsed.get("capabilities") or []
    if PULSE.search(text) and kind in ("UNROUTABLE", "NEEDS_SUBJECT") and not \
            (parsed.get("clarification") or "").startswith("I do not pick names"):
        return "PULSE"
    if kind == "QUERY" and caps == ["market_regime"] and LIVE.search(text):
        return "PULSE"
    clar = parsed.get("clarification") or ""
    if kind == "NEEDS_SUBJECT" and clar.startswith("I do not pick names"):
        return None                                   # the no-pick refusal stands
    named = bool(parsed.get("symbols")) and not parsed.get("symbols_from_context")
    if kind == "QUERY" and named and NEWS.search(text):
        return "NEWS"
    if kind == "NEEDS_SUBJECT" and CONCEPT.search(text):
        return "CONCEPT"
    if kind == "UNROUTABLE" and (CONCEPT.search(text) or NEWS.search(text) or "?" in text
                                 or lk.FredFetcher(lk.MARKET_SERIES)._wanted(text) or len(lk.terms(text)) >= 3):
        return "UNROUTABLE"                           # a question, not "asdfgh"
    return None


def answer(text: str, symbols: Optional[List[str]] = None, shape_: str = "UNROUTABLE") -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"tickers": [s for s in (symbols or []) if s][:3]}
    if shape_ == "NEWS" or NEWS.search(text):
        ctx["want_news"] = True
    if shape_ == "NEWS":
        ctx["only"] = ["news", "sec"]      # the live_market agent states the price; this one finds the why
    return pipeline().answer(text, ctx)


def block(k: Dict[str, Any]) -> Dict[str, Any]:
    """A reply block in the same shape as the specialists' blocks."""
    lines = [k["answer"]]
    if k.get("sources"):
        lines.append("Sources: " + "; ".join(
            f"[{s['n']}] {s['title']} — {s['source']}, {s['fetched_at']}" for s in k["sources"]))
    return {"capability": "live_knowledge", "answered_by": "live_knowledge", "lines": lines,
            "sources": k.get("sources") or [], "used_live": k.get("used_live"), "found": k.get("found")}
