"""
FIL provider — real-time US quotes via Finnhub. Key-gated on FINNHUB_API_KEY.

Registered ABOVE the keyless providers by priority so that the moment a key
lands in .env the whole system's quotes get better without a code change —
that is the point of the registry-as-data seam. Absent the key this raises
NotConfiguredError and the gateway falls through to yfinance-rt, naming the
missing variable in a warning rather than silently serving a worse quote.

Finnhub's /quote is a genuine real-time US consolidated last trade on the free
tier (60 req/min), which is the specific upgrade this slot exists to receive.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..keys import NotConfiguredError, get_key
from ..schemas import make_datum, make_source
from ._http import get_text

KINDS = ("quote",)

BASE = "https://finnhub.io/api/v1/quote?symbol={sym}&token={token}"


class ProviderError(RuntimeError):
    pass


def fetch(kind: str, symbols: List[str], start: Optional[str] = None,
          end: Optional[str] = None, as_of: Optional[str] = None,
          reliability: float = 0.9, **kwargs: Any) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ProviderError(f"finnhub does not serve kind {kind!r}")

    token = get_key("FINNHUB_API_KEY", "finnhub-quote")   # raises NotConfiguredError

    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if as_of:
        warnings.append("a quote cannot be served as-of a past instant; "
                        "as_of_honored is False")

    for sym in symbols:
        s = sym.upper()
        try:
            raw = json.loads(get_text(BASE.format(sym=s, token=token), timeout=10))
            price = float(raw.get("c") or 0)
            # Finnhub returns c=0 for an unknown symbol rather than an error.
            # Treating 0 as a price would put a zero into a prediction.
            if price <= 0:
                raise ProviderError("finnhub returned no current price (c=0); "
                                    "the symbol may not be covered")
            ts = raw.get("t")
            stamp = (datetime.fromtimestamp(float(ts), tz=timezone.utc)
                     if ts else datetime.now(timezone.utc))
            extra: Dict[str, Any] = {"interval": None}
            if raw.get("pc"):
                pc = float(raw["pc"])
                if pc > 0:
                    extra["previous_close"] = pc
                    extra["change_pct"] = round((price / pc - 1.0) * 100.0, 4)
            for src, dst in (("o", "open"), ("h", "high"), ("l", "low")):
                if raw.get(src):
                    extra[dst] = float(raw[src])
            data.append(make_datum(
                kind="quote", value=price, available_at=stamp,
                source=make_source(provider="finnhub", document=f"{s}:quote",
                                   ref="api/v1/quote.c"),
                symbol=s, concept="last_trade", unit="USD",
                confidence=reliability, status="actual", extra=extra))
        except NotConfiguredError:
            raise
        except Exception as e:
            unavailable.append({"symbol": s, "kind": kind,
                                "reason": f"{type(e).__name__}: {e}"})

    return {"data": data, "unavailable": unavailable, "warnings": warnings}
