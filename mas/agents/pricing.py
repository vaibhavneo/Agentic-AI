"""
Price discovery — numbers only, no prose.

Registered in the slot the `social` pillar used to occupy, and the swap is
evidence-driven rather than a preference. Measured across the ledger, social
carried a correlation with forward return of +0.016 at 5 days, -0.026 at 20
days, and had no observations at all at 60 — on samples of 250, 14 and 0. It was
a modifier worth at most 5 composite points and it never earned them. Its input
was flagged `reddit_sample_too_small` on the last name the desk looked at.

What replaces it is deliberately the opposite kind of agent: every field is a
number with a stated source, and nothing here writes a sentence for a human to
weigh. Four readings, each answering a question the desk previously could not:

  SPOT      a live price with its corroboration grade, so a bad print is
            visible rather than averaged in. CROSS_VENDOR means independent
            feeds agree; CROSS_PATH means two routes to one vendor, which rules
            out a stale cache and nothing else.

  VOL GAP   implied volatility from the listed chain against realized
            volatility from the bars. This is the number the desk was missing
            entirely: it priced options from realized vol, and on IONQ that was
            8.6 points below what the market charged, worth about 10% of the
            contract. The SIGN of the gap is the reading — implied above
            realized means the market expects more movement than has occurred.

  INTRADAY  where price sits inside its own recent range, at bar resolution.

  HORIZON   a structural read at three horizons. Structural, not predictive:
            distance to levels the price has actually traded, and the
            volatility that scales them. This agent states no probability and
            makes no forecast, because nothing in this system has demonstrated
            an edge that would justify one.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..contract import AgentRequest
from ..contract import ok, unavailable

AGENT_ID = "pricing"
CAPABILITY = "price_discovery"

MIN_BARS = 60

# Horizon labels and their trading-day spans, matching the desk's own vocabulary.
HORIZONS = (("SHORT", 5), ("MEDIUM", 21), ("LONG", 126))


def available() -> Dict[str, Any]:
    """Keyless: the chain, the quote and the bars all come from free sources."""
    return {"available": True, "reason": ""}


def _bars(symbol: str, period: str = "1y"):
    from financial_data.gateway import get_bars_df
    return get_bars_df(symbol, period=period)


def _realized_vol_pct(closes, days_per_year: int, window: int = 30
                      ) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    rets = closes.pct_change().dropna().tail(window)
    if len(rets) < 5:
        return None
    return float(rets.std() * math.sqrt(days_per_year) * 100.0)


def _implied_vol_pct(symbol: str) -> Dict[str, Any]:
    """At-the-money implied vol from the listed chain, or a stated absence."""
    try:
        from financial_data.gateway import get
        r = get("option_chain", symbol)
        d = (r.get("data") or [None])[0]
        if not d or not d.get("value"):
            return {"available": False,
                    "reason": ((r.get("unavailable") or [{}])[0].get("reason")
                               or "the chain returned no implied volatility")}
        ex = d.get("extra") or {}
        return {"available": True, "implied_pct": round(float(d["value"]) * 100, 2),
                "expiration": ex.get("expiration"),
                "n_contracts": (ex.get("n_calls") or 0) + (ex.get("n_puts") or 0)}
    except Exception as e:
        return {"available": False, "reason": f"{type(e).__name__}"}


def _levels(closes) -> Dict[str, Any]:
    """Structural levels from where price has actually been."""
    import pandas as pd
    tail = closes.tail(252)
    return {
        "last": round(float(closes.iloc[-1]), 4),
        "high_52w": round(float(tail.max()), 4),
        "low_52w": round(float(tail.min()), 4),
        "range_position_pct": round(
            100.0 * (float(closes.iloc[-1]) - float(tail.min()))
            / max(1e-9, float(tail.max()) - float(tail.min())), 1),
        "ma20": round(float(closes.rolling(20).mean().iloc[-1]), 4),
        "ma50": round(float(closes.rolling(50).mean().iloc[-1]), 4)
        if len(closes) >= 50 else None,
        "ma200": round(float(closes.rolling(200).mean().iloc[-1]), 4)
        if len(closes) >= 200 else None,
    }


def _horizon_reads(closes, vol_pct: Optional[float],
                   days_per_year: int) -> List[Dict[str, Any]]:
    """One structural read per horizon. No probability, no forecast.

    The move a horizon can hold is vol scaled by sqrt(time) — the only honest
    way to put a volatility on a horizon. It is a WIDTH, not a direction, and it
    is labelled as such: a one-standard-deviation band says where price can
    plausibly be, never where it is going.
    """
    out = []
    last = float(closes.iloc[-1])
    for label, days in HORIZONS:
        if len(closes) <= days:
            out.append({"horizon": label, "trading_days": days,
                        "status": "INSUFFICIENT_HISTORY"})
            continue
        trailing = (last / float(closes.iloc[-1 - days]) - 1.0) * 100.0
        band = ((vol_pct / 100.0) * math.sqrt(days / float(days_per_year)) * last
                if vol_pct else None)
        out.append({
            "horizon": label, "trading_days": days, "status": "OK",
            "trailing_return_pct": round(trailing, 2),
            "one_sd_move_pct": (round(100.0 * band / last, 2) if band else None),
            "one_sd_band": ([round(last - band, 2), round(last + band, 2)]
                            if band else None),
            "basis": ("volatility scaled by sqrt(time) — a WIDTH the horizon can "
                      "hold, not a direction it will take"),
        })
    return out


def run(request: AgentRequest) -> Any:
    """Price discovery for one symbol. Every field is a number or a stated gap."""
    if request.capability != CAPABILITY:
        return unavailable(AGENT_ID, request.capability,
                           f"{AGENT_ID} serves only {CAPABILITY}")

    symbol = (request.symbol or "").upper().strip()
    if not symbol:
        return unavailable(AGENT_ID, request.capability,
                           "price discovery needs a symbol")

    from ..asset_class import spec_for
    spec = spec_for(request.asset_class)

    try:
        df = _bars(symbol)
    except Exception as e:
        return unavailable(AGENT_ID, request.capability,
                           f"price history could not be read ({type(e).__name__})")
    if df is None or len(df) < MIN_BARS:
        return unavailable(AGENT_ID, request.capability,
                           f"only {0 if df is None else len(df)} bars available; "
                           f"{MIN_BARS} are needed")
    closes = df["Close"].astype(float)

    from ..realtime import consensus
    spot = consensus(symbol, asset_class=spec.asset_class)

    realized = _realized_vol_pct(closes, spec.days_per_year)
    implied = _implied_vol_pct(symbol)

    vol_gap = None
    if implied.get("available") and realized:
        gap = implied["implied_pct"] - realized
        vol_gap = {
            "implied_pct": implied["implied_pct"],
            "realized_pct": round(realized, 2),
            "gap_points": round(gap, 2),
            # The sign is the reading. Stated rather than left to the reader,
            # because the same number means opposite things either way.
            "reading": ("the market is pricing MORE movement than this name has "
                        "delivered" if gap > 0 else
                        "the market is pricing LESS movement than this name has "
                        "delivered"),
            "expiration": implied.get("expiration"),
        }

    # Which volatility the horizon bands use. Implied where the market gave one,
    # because a forward-looking band built on a backward-looking number is the
    # same mistake the option engine was making.
    band_vol = (implied["implied_pct"] if implied.get("available") else realized)
    band_basis = "IMPLIED_BY_CHAIN" if implied.get("available") else "REALIZED_30_BAR"

    return ok(AGENT_ID, request.capability, {
        "symbol": symbol,
        "asset_class": spec.asset_class,
        "spot": {
            "price": spot.get("price"),
            "confirmation": spot.get("confirmation"),
            "usable": spot.get("usable"),
            "n_sources": spot.get("n_sources"),
            "spread_pct": spot.get("spread_pct"),
            "statement": spot.get("statement"),
        },
        "volatility": {
            "realized_30_bar_pct": round(realized, 2) if realized else None,
            "implied_atm_pct": implied.get("implied_pct"),
            "implied_available": implied.get("available"),
            "implied_absent_reason": (None if implied.get("available")
                                      else implied.get("reason")),
            "annualization_days": spec.days_per_year,
            "gap": vol_gap,
        },
        "levels": _levels(closes),
        "horizons": _horizon_reads(closes, band_vol, spec.days_per_year),
        "band_volatility_basis": band_basis,
        "no_forecast": ("Every figure here is a measurement or a structural "
                        "distance. This agent states no probability and makes no "
                        "forecast: nothing in this system has demonstrated a "
                        "forward edge that would justify one."),
    }, price_basis="TRADED_PRICE" if spot.get("usable") else "PRICE_HISTORY_DERIVED")
