"""
FIL provider — real-time quotes and intraday bars via yfinance.

Separate module from yfinance_bars on purpose. Daily bars and live quotes have
opposite truth conditions and putting them behind one module hides that:

  - a daily bar is SETTLED. Once the session closes it stops moving, it is
    point-in-time correct, and a backtest may lean on it.
  - a quote is a MOMENT. It cannot be replayed, it can be a bad print, and no
    backtest may ever consult it.

The registry reflects that: this provider declares `quote` outside its
pit_capable list, so the gateway stamps as_of_honored=False on every quote and
the caller is told rather than left to assume.

Intraday IS point-in-time capable, but only inside the retention window —
yfinance serves roughly 30 days of 1-minute bars and 60 days of 5-minute. Ask
for older and the vendor returns an empty frame, which this module reports as
an explicit unavailability rather than as "no trades occurred".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..schemas import make_datum, make_source

KINDS = ("quote", "intraday")

# Vendor retention, in calendar days, per interval. Asking beyond this returns
# empty — naming the limit turns a silent empty frame into a stated reason.
RETENTION_DAYS = {"1m": 30, "2m": 60, "5m": 60, "15m": 60, "30m": 60,
                  "60m": 730, "90m": 60, "1h": 730}

DEFAULT_INTERVAL = "5m"


class ProviderError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _quote_one(sym: str, reliability: float) -> Dict[str, Any]:
    """One symbol's last trade, or a typed reason why not."""
    import yfinance as yf

    t = yf.Ticker(sym)
    price = prev_close = None
    try:
        fi = t.fast_info
        price = fi.get("lastPrice") or fi.get("last_price")
        prev_close = fi.get("previousClose") or fi.get("previous_close")
    except Exception:
        price = None

    if not price:
        raise ProviderError("the provider returned no last trade")

    price = float(price)
    # A quote of zero or a negative is a bad print, not a price. Rejecting it
    # here keeps a corrupt tick from reaching a prediction, which is the one
    # failure mode a real-time path adds over a settled one.
    if price <= 0:
        raise ProviderError(f"implausible last trade {price!r}")

    now = _now()
    extra: Dict[str, Any] = {"interval": None}
    if prev_close:
        try:
            pc = float(prev_close)
            if pc > 0:
                extra["previous_close"] = pc
                extra["change_pct"] = round((price / pc - 1.0) * 100.0, 4)
        except Exception:
            pass

    return make_datum(
        kind="quote",
        value=price,
        available_at=now,
        source=make_source(provider="yfinance-rt",
                           document=f"{sym}:quote",
                           ref="fast_info.lastPrice"),
        symbol=sym,
        concept="last_trade",
        unit="USD",
        confidence=reliability,
        status="actual",
        extra=extra,
    )


def _intraday_one(sym: str, interval: str, period: str,
                  reliability: float) -> List[Dict[str, Any]]:
    import yfinance as yf

    df = yf.Ticker(sym).history(period=period, interval=interval)
    if df is None or df.empty:
        raise ProviderError(
            f"no {interval} bars returned for period {period!r} "
            f"(vendor retention for {interval} is about "
            f"{RETENTION_DAYS.get(interval, '?')} days)")

    out: List[Dict[str, Any]] = []
    for ts, row in df.iterrows():
        try:
            close = float(row["Close"])
        except Exception:
            continue
        if close <= 0:
            continue
        stamp = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        out.append(make_datum(
            kind="intraday",
            value=close,
            # An intraday bar is knowable at the END of its interval, which is
            # its index timestamp. Stamping it at the start would make a
            # replay able to act on a bar before it finished forming.
            available_at=stamp,
            source=make_source(provider="yfinance-rt",
                               document=f"{sym}:{interval}:{stamp}",
                               ref="history.Close"),
            symbol=sym,
            concept="close",
            unit="USD",
            period_end=stamp,
            confidence=reliability,
            status="actual",
            extra={"open": float(row.get("Open", close)),
                   "high": float(row.get("High", close)),
                   "low": float(row.get("Low", close)),
                   "volume": float(row.get("Volume", 0) or 0),
                   "interval": interval},
        ))
    return out


def fetch(kind: str, symbols: List[str], start: Optional[str] = None,
          end: Optional[str] = None, as_of: Optional[str] = None,
          period: str = "1d", interval: Optional[str] = None,
          reliability: float = 0.6, **kwargs: Any) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ProviderError(f"yfinance-rt does not serve kind {kind!r}")

    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    warnings: List[str] = []

    if kind == "quote" and as_of:
        warnings.append(
            "a quote cannot be served as-of a past instant; this is the "
            "current last trade and as_of_honored is False")

    iv = interval or DEFAULT_INTERVAL

    for sym in symbols:
        try:
            if kind == "quote":
                data.append(_quote_one(sym, reliability))
            else:
                data.extend(_intraday_one(sym, iv, period, reliability))
        except Exception as e:
            unavailable.append({"symbol": sym, "kind": kind,
                                "reason": f"{type(e).__name__}: {e}"})

    return {"data": data, "unavailable": unavailable, "warnings": warnings}
