"""
FIL provider — Finnhub's free-tier research endpoints (key-gated, FINNHUB_API_KEY).

  events     concept earnings_surprise       /stock/earnings — reported EPS vs
                                              consensus for recent quarters
  sentiment  concept analyst_recommendation  /stock/recommendation — monthly
                                              strong-buy … strong-sell counts
  filings    concept insider_transaction     /stock/insider-transactions —
                                              Form 4 trades, parsed
  universe   concept peers                   /stock/peers

Callers name this provider explicitly (provider="finnhub-research"): the SEC
provider also serves `filings`, and the gateway's fall-through would otherwise
hand a caller asking for insider trades the SEC filing index.

No key → NotConfiguredError naming the variable; the Stock Analysis report
says the section is waiting for FINNHUB_API_KEY rather than showing empties.
Free tier: 60 calls/minute; responses are cached (6 hours, peers 7 days).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from .. import cache
from ..keys import NotConfiguredError, get_key
from ..schemas import make_datum, make_source

KINDS = ("events", "sentiment", "filings", "universe")
BASE = "https://finnhub.io/api/v1"
_MIN_INTERVAL = 1.05          # free tier: 60/minute
_last = [0.0]


class ProviderError(RuntimeError):
    pass


def _get(path: str, params: Dict[str, Any], max_age: int) -> Any:
    key = path.strip("/").replace("/", "_") + "_" + "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
    hit = cache.get("finnhub", "research", key, max_age_sec=max_age)
    if hit is not None:
        return hit
    token = get_key("FINNHUB_API_KEY", "finnhub-research")
    wait = _MIN_INTERVAL - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    url = f"{BASE}{path}?{urllib.parse.urlencode(dict(params, token=token))}"
    req = urllib.request.Request(url, headers={"User-Agent": "AIOS-StockAgent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise NotConfiguredError(f"Finnhub rejected FINNHUB_API_KEY for {path} (HTTP {e.code}) — "
                                     "the endpoint may need a paid plan") from e
        raise ProviderError(f"finnhub HTTP {e.code} for {path}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"finnhub unreachable: {e}") from e
    cache.put("finnhub", "research", key, payload)
    return payload


def fetch(kind: str, symbols: List[str], start: Optional[str] = None, end: Optional[str] = None,
          as_of: Optional[str] = None, concepts: Optional[List[str]] = None, reliability: float = 0.8,
          **kwargs: Any) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ProviderError(f"finnhub-research does not serve kind {kind!r}")
    what = (concepts or [None])[0]
    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    now = datetime.now()
    for sym in symbols:
        sym = sym.upper().strip()
        try:
            if kind == "events" and what in (None, "earnings_surprise"):
                rows = _get("/stock/earnings", {"symbol": sym}, 6 * 3600) or []
                for r in rows:
                    if r.get("actual") is None or not r.get("period"):
                        continue
                    data.append(make_datum(
                        kind="events", value=float(r["actual"]), available_at=r["period"],
                        source=make_source("finnhub-research", document=f"earnings:{sym}:{r['period']}",
                                           ref="stock/earnings"),
                        symbol=sym, concept="earnings_surprise", unit="USD_per_share", period_end=r["period"],
                        confidence=reliability, status="actual",
                        extra={"estimate": r.get("estimate"), "surprise": r.get("surprise"),
                               "surprise_pct": r.get("surprisePercent"), "quarter": r.get("quarter"),
                               "year": r.get("year"),
                               "note": "available_at is the quarter end; the report date is later"}))
            elif kind == "sentiment" and what in (None, "analyst_recommendation"):
                rows = _get("/stock/recommendation", {"symbol": sym}, 6 * 3600) or []
                for r in rows:
                    if not r.get("period"):
                        continue
                    total = sum(int(r.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
                    data.append(make_datum(
                        kind="sentiment", value=total, available_at=r["period"],
                        source=make_source("finnhub-research", document=f"recs:{sym}:{r['period']}",
                                           ref="stock/recommendation"),
                        symbol=sym, concept="analyst_recommendation", unit="analysts", period_end=r["period"],
                        confidence=reliability, status="estimate",
                        extra={k: int(r.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}))
            elif kind == "filings" and what in (None, "insider_transaction"):
                payload = _get("/stock/insider-transactions", {"symbol": sym}, 6 * 3600) or {}
                for r in payload.get("data") or []:
                    filed = r.get("filingDate") or r.get("transactionDate")
                    if not filed or r.get("change") is None:
                        continue
                    data.append(make_datum(
                        kind="filings", value=float(r["change"]), available_at=filed,
                        source=make_source("finnhub-research", document=f"form4:{sym}:{r.get('name')}:{filed}",
                                           ref="stock/insider-transactions"),
                        symbol=sym, concept="insider_transaction", unit="shares",
                        period_end=r.get("transactionDate"), confidence=reliability, status="actual",
                        extra={"name": r.get("name"), "code": r.get("transactionCode"),
                               "price": r.get("transactionPrice"), "shares_after": r.get("share"),
                               "is_derivative": r.get("isDerivative")}))
            elif kind == "universe" and what in (None, "peers"):
                peers = _get("/stock/peers", {"symbol": sym}, 7 * 86400) or []
                for p in peers:
                    if p and p.upper() != sym:
                        data.append(make_datum(
                            kind="universe", value=str(p).upper(), available_at=now,
                            source=make_source("finnhub-research", document=f"peers:{sym}", ref="stock/peers"),
                            symbol=sym, concept="peers", confidence=reliability, status="actual"))
            else:
                raise ProviderError(f"finnhub-research: no concept {what!r} for kind {kind!r}")
        except ProviderError as e:
            unavailable.append({"symbol": sym, "reason": str(e)})
    return {"data": data, "unavailable": unavailable, "warnings": []}
