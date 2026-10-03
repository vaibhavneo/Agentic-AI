"""
FIL provider — Alpha Vantage (key-gated, ALPHAVANTAGE_API_KEY; free tier 25
requests/day, so every response is cached for a day or more).

  events    concept earnings_surprise   EARNINGS — reported vs ESTIMATED EPS for
                                         every quarter on record, with the report
                                         date: a consensus history Finnhub's free
                                         tier (four quarters) cannot give
  filings   concept call_transcript      EARNINGS_CALL_TRANSCRIPT (quarter=YYYYQn, the
                                         COMPANY'S fiscal quarter: Nvidia's May 2026
                                         call is 2027Q1). Recent calls can lag weeks.

Alpha Vantage signals limits and plan restrictions in-band ("Note"/
"Information" keys with HTTP 200); those become a ProviderError naming the
reason, never an empty success. Callers name this provider explicitly.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .. import cache
from ..keys import get_key
from ..schemas import make_datum, make_source

KINDS = ("events", "filings")
BASE = "https://www.alphavantage.co/query"


# The free tier refuses a second request within a second (in-band
# "Information" body); one report makes two calls back to back.
MIN_SPACING_SEC = 1.1
_lock = threading.Lock()
_last = [0.0]


class ProviderError(RuntimeError):
    pass


def _throttle() -> None:
    with _lock:
        wait = _last[0] + MIN_SPACING_SEC - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def _get(params: Dict[str, str], max_age: int, keep: Optional[Callable[[Dict[str, Any]], bool]] = None,
         empty_max_age: int = 86400) -> Dict[str, Any]:
    """`keep` says whether a response is worth the long cache: an empty answer
    ("no transcript yet") is held for a day only, so it is asked again."""
    key = "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
    hit = cache.get("alphavantage", "api", key, max_age_sec=max_age)
    if hit is not None and (keep is None or keep(hit)):
        return hit
    if keep is not None:
        miss = cache.get("alphavantage", "api", key + "__empty", max_age_sec=empty_max_age)
        if miss is not None:
            return miss
    token = get_key("ALPHAVANTAGE_API_KEY", "alphavantage")
    _throttle()
    url = BASE + "?" + urllib.parse.urlencode(dict(params, apikey=token))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AIOS-StockAgent/1.0"}),
                                    timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise ProviderError(f"alphavantage unreachable: {e}") from e
    for k in ("Note", "Information", "Error Message"):
        if isinstance(payload, dict) and k in payload and len(payload) <= 2:
            raise ProviderError(f"alphavantage: {payload[k][:160]}")
    cache.put("alphavantage", "api", key if keep is None or keep(payload) else key + "__empty", payload)
    return payload


def fetch(kind: str, symbols: List[str], start: Optional[str] = None, end: Optional[str] = None,
          as_of: Optional[str] = None, concepts: Optional[List[str]] = None, reliability: float = 0.75,
          **kwargs: Any) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ProviderError(f"alphavantage does not serve kind {kind!r}")
    what = (concepts or [None])[0]
    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    for sym in symbols:
        sym = sym.upper()
        try:
            if kind == "events" and what in (None, "earnings_surprise"):
                p = _get({"function": "EARNINGS", "symbol": sym}, 86400)
                for r in p.get("quarterlyEarnings") or []:
                    rep, est = r.get("reportedEPS"), r.get("estimatedEPS")
                    when = r.get("reportedDate") or r.get("fiscalDateEnding")
                    try:
                        rep_f = float(rep)
                    except (TypeError, ValueError):
                        continue
                    try:
                        est_f = float(est)
                    except (TypeError, ValueError):
                        est_f = None
                    data.append(make_datum(
                        kind="events", value=rep_f, available_at=when,
                        source=make_source("alphavantage", document=f"earnings:{sym}:{r.get('fiscalDateEnding')}",
                                           ref="EARNINGS"),
                        symbol=sym, concept="earnings_surprise", unit="USD_per_share",
                        period_end=r.get("fiscalDateEnding"), confidence=reliability, status="actual",
                        extra={"estimate": est_f, "surprise_pct": _f(r.get("surprisePercentage")),
                               "reported_date": r.get("reportedDate"), "report_time": r.get("reportTime")}))
            elif kind == "filings" and what == "call_transcript":
                q = kwargs.get("quarter")
                if not q:
                    raise ProviderError("call_transcript needs quarter='YYYYQn'")
                p = _get({"function": "EARNINGS_CALL_TRANSCRIPT", "symbol": sym, "quarter": q}, 30 * 86400,
                         keep=lambda x: bool(x.get("transcript")))
                parts = p.get("transcript") or []
                if not parts:
                    raise ProviderError(f"no transcript for {sym} {q}")
                text = "\n".join(f"{x.get('speaker', '')} ({x.get('title', '')}): {x.get('content', '')}" for x in parts)
                data.append(make_datum(
                    kind="filings", value=text, available_at=kwargs.get("filed") or "1994-01-01",
                    source=make_source("alphavantage", document=f"transcript:{sym}:{q}", ref="EARNINGS_CALL_TRANSCRIPT"),
                    symbol=sym, concept="call_transcript", unit="text", confidence=reliability, status="actual",
                    extra={"quarter": q, "speakers": len(parts)}))
            else:
                raise ProviderError(f"alphavantage: no concept {what!r} for kind {kind!r}")
        except ProviderError as e:
            unavailable.append({"symbol": sym, "reason": str(e)})
    return {"data": data, "unavailable": unavailable, "warnings": []}


def _f(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
