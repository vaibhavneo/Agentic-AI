"""
FIL provider — quote and intraday via Yahoo's chart JSON endpoint.

Deliberately a DIFFERENT CODE PATH to the same vendor as yfinance-rt, and the
notes say so rather than overselling it. What it can and cannot catch:

  CAN catch — a stale or poisoned yfinance `fast_info` cache, a library-side
  schema drift, a symbol the library resolves differently. These are real: the
  registry already records yfinance "unannounced schema drift" as the reason
  its reliability is 0.6.

  CANNOT catch — a vendor-wide bad print. Both read Yahoo. Genuine cross-vendor
  disagreement for equities needs FINNHUB_API_KEY, and `realtime.consensus()`
  says exactly that instead of implying two same-vendor sources agreeing means
  the price is confirmed.

Stooq held this slot until 2026-09-24, when it went behind a JavaScript
proof-of-work challenge and stopped answering programmatic requests at all. A
provider that cannot answer is worse than no provider, so it was removed rather
than left registered and permanently failing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..schemas import make_datum, make_source
from ._http import get_text

KINDS = ("quote", "intraday")

BASE = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        "?interval={interval}&range={rng}")

RETENTION_DAYS = {"1m": 30, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 730}


class ProviderError(RuntimeError):
    pass


def _chart(sym: str, interval: str, rng: str) -> Dict[str, Any]:
    raw = json.loads(get_text(BASE.format(sym=sym, interval=interval, rng=rng),
                              timeout=12))
    chart = raw.get("chart") or {}
    if chart.get("error"):
        raise ProviderError(f"yahoo chart error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise ProviderError("yahoo chart returned no result block")
    return results[0]


def _quote_one(sym: str, reliability: float) -> Dict[str, Any]:
    res = _chart(sym, "1m", "1d")
    meta = res.get("meta") or {}
    price = meta.get("regularMarketPrice")
    if not price:
        raise ProviderError("no regularMarketPrice in the chart meta block")
    price = float(price)
    if price <= 0:
        raise ProviderError(f"implausible price {price!r}")

    ts = meta.get("regularMarketTime")
    stamp = (datetime.fromtimestamp(float(ts), tz=timezone.utc)
             if ts else datetime.now(timezone.utc))
    extra: Dict[str, Any] = {"interval": None,
                             "exchange": meta.get("fullExchangeName"),
                             "currency": meta.get("currency")}
    if meta.get("chartPreviousClose"):
        pc = float(meta["chartPreviousClose"])
        if pc > 0:
            extra["previous_close"] = pc
            extra["change_pct"] = round((price / pc - 1.0) * 100.0, 4)
    return make_datum(
        kind="quote", value=price, available_at=stamp,
        source=make_source(provider="yahoo-chart", document=f"{sym}:quote",
                           ref="chart.meta.regularMarketPrice"),
        symbol=sym, concept="last_trade", unit="USD",
        confidence=reliability, status="actual", extra=extra)


def _intraday_one(sym: str, interval: str, rng: str,
                  reliability: float) -> List[Dict[str, Any]]:
    res = _chart(sym, interval, rng)
    stamps = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    if not stamps or not closes:
        raise ProviderError(
            f"no {interval} bars for range {rng!r} (vendor retention for "
            f"{interval} is about {RETENTION_DAYS.get(interval, '?')} days)")

    opens, highs = quote.get("open") or [], quote.get("high") or []
    lows, vols = quote.get("low") or [], quote.get("volume") or []
    out: List[Dict[str, Any]] = []
    for i, ts in enumerate(stamps):
        c = closes[i] if i < len(closes) else None
        # Yahoo pads gaps with nulls. A null is a missing bar, not a zero price.
        if c is None or float(c) <= 0:
            continue
        stamp = datetime.fromtimestamp(float(ts), tz=timezone.utc)

        def _at(seq, default):
            v = seq[i] if i < len(seq) else None
            return float(v) if v is not None else default

        out.append(make_datum(
            kind="intraday", value=float(c), available_at=stamp,
            source=make_source(provider="yahoo-chart",
                               document=f"{sym}:{interval}:{stamp.isoformat()}",
                               ref="chart.indicators.quote.close"),
            symbol=sym, concept="close", unit="USD", period_end=stamp,
            confidence=reliability, status="actual",
            extra={"open": _at(opens, float(c)), "high": _at(highs, float(c)),
                   "low": _at(lows, float(c)), "volume": _at(vols, 0.0),
                   "interval": interval}))
    if not out:
        raise ProviderError(f"every {interval} bar in range {rng!r} was null")
    return out


# yfinance-style period strings -> yahoo chart `range` strings.
_RANGE = {"1d": "1d", "5d": "5d", "1mo": "1mo", "3mo": "3mo", "6mo": "6mo",
          "1y": "1y", "2y": "2y", "5y": "5y", "max": "max"}


def fetch(kind: str, symbols: List[str], start: Optional[str] = None,
          end: Optional[str] = None, as_of: Optional[str] = None,
          period: str = "1d", interval: Optional[str] = None,
          reliability: float = 0.6, **kwargs: Any) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ProviderError(f"yahoo-chart does not serve kind {kind!r}")

    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if kind == "quote" and as_of:
        warnings.append("a quote cannot be served as-of a past instant; "
                        "as_of_honored is False")

    iv = interval or "5m"
    rng = _RANGE.get(period, period)
    for sym in symbols:
        s = sym.upper()
        try:
            if kind == "quote":
                data.append(_quote_one(s, reliability))
            else:
                data.extend(_intraday_one(s, iv, rng, reliability))
        except Exception as e:
            unavailable.append({"symbol": s, "kind": kind,
                                "reason": f"{type(e).__name__}: {e}"})
    return {"data": data, "unavailable": unavailable, "warnings": warnings}
