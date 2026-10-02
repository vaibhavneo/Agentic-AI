"""
FIL provider — Financial Modeling Prep (key-gated, FMP_API_KEY; free tier ~250
requests/day, cached).

  events    concept earnings_surprise   /stable/earnings — actual vs estimated EPS
                                         and revenue by report date
  filings   concept call_transcript      /stable/earning-call-transcript
                                         (year=, quarter=) — on plans that include it

A plan restriction (HTTP 402/403, or a JSON "Error Message") becomes a
ProviderError naming it. Callers name this provider explicitly.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .. import cache
from ..keys import NotConfiguredError, get_key
from ..schemas import make_datum, make_source

KINDS = ("events", "filings")
BASE = "https://financialmodelingprep.com/stable"


class ProviderError(RuntimeError):
    pass


def _get(path: str, params: Dict[str, Any], max_age: int) -> Any:
    key = path.strip("/").replace("/", "_") + "_" + "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
    hit = cache.get("fmp", "api", key, max_age_sec=max_age)
    if hit is not None:
        return hit
    token = get_key("FMP_API_KEY", "fmp")
    url = f"{BASE}{path}?{urllib.parse.urlencode(dict(params, apikey=token))}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AIOS-StockAgent/1.0"}),
                                    timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise NotConfiguredError(f"FMP rejected FMP_API_KEY for {path} (HTTP {e.code})") from e
        if e.code == 402:
            raise ProviderError(f"fmp: {path} needs a paid plan (HTTP 402)") from e
        raise ProviderError(f"fmp HTTP {e.code} for {path}") from e
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise ProviderError(f"fmp unreachable: {e}") from e
    if isinstance(payload, dict) and payload.get("Error Message"):
        raise ProviderError(f"fmp: {payload['Error Message'][:160]}")
    cache.put("fmp", "api", key, payload)
    return payload


def fetch(kind: str, symbols: List[str], start: Optional[str] = None, end: Optional[str] = None,
          as_of: Optional[str] = None, concepts: Optional[List[str]] = None, reliability: float = 0.75,
          **kwargs: Any) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ProviderError(f"fmp does not serve kind {kind!r}")
    what = (concepts or [None])[0]
    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    for sym in symbols:
        sym = sym.upper()
        try:
            if kind == "events" and what in (None, "earnings_surprise"):
                rows = _get("/earnings", {"symbol": sym}, 86400) or []
                for r in rows:
                    if r.get("epsActual") is None or not r.get("date"):
                        continue
                    data.append(make_datum(
                        kind="events", value=float(r["epsActual"]), available_at=r["date"],
                        source=make_source("fmp", document=f"earnings:{sym}:{r['date']}", ref="earnings"),
                        symbol=sym, concept="earnings_surprise", unit="USD_per_share", period_end=r["date"],
                        confidence=reliability, status="actual",
                        extra={"estimate": r.get("epsEstimated"), "revenue_actual": r.get("revenueActual"),
                               "revenue_estimate": r.get("revenueEstimated"), "reported_date": r.get("date")}))
            elif kind == "filings" and what == "call_transcript":
                year, quarter = kwargs.get("year"), kwargs.get("quarter")
                if not year or not quarter:
                    raise ProviderError("call_transcript needs year= and quarter=")
                rows = _get("/earning-call-transcript", {"symbol": sym, "year": year, "quarter": quarter},
                            30 * 86400) or []
                if not rows:
                    raise ProviderError(f"no transcript for {sym} {year}Q{quarter}")
                r = rows[0]
                data.append(make_datum(
                    kind="filings", value=r.get("content") or "", available_at=(r.get("date") or "1994-01-01")[:10],
                    source=make_source("fmp", document=f"transcript:{sym}:{year}Q{quarter}", ref="earning-call-transcript"),
                    symbol=sym, concept="call_transcript", unit="text", confidence=reliability, status="actual",
                    extra={"year": year, "quarter": quarter}))
            else:
                raise ProviderError(f"fmp: no concept {what!r} for kind {kind!r}")
        except ProviderError as e:
            unavailable.append({"symbol": sym, "reason": str(e)})
    return {"data": data, "unavailable": unavailable, "warnings": []}
