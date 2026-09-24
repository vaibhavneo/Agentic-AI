"""
Real-time price with an honest confirmation status.

Moving predictions from settled bars to live quotes adds exactly one new
failure mode: a BAD PRINT. A settled daily close has been through the venue's
own correction process; a last trade has not. A single erroneous tick that
reaches a prediction produces a confident, fully-provenanced, wrong answer —
the worst output this system can make.

So nothing here returns a bare price. Every result carries a CONFIRMATION
status saying how much corroboration the number actually has, and callers are
expected to branch on it:

  CROSS_VENDOR  two independent vendors agree inside tolerance. Safe to predict on.
  CROSS_PATH    two code paths to the SAME vendor agree. Catches a stale cache
                or library drift; does NOT rule out a vendor-wide bad print.
  SINGLE        one source answered. Usable, uncorroborated, and says so.
  DISAGREEMENT  sources differ beyond tolerance. The price is NOT returned as
                usable — this is the case the layer exists for.
  UNAVAILABLE   nothing answered.

The distinction between CROSS_VENDOR and CROSS_PATH is the whole point. For US
equities this system has only same-vendor keyless sources, so equities top out
at CROSS_PATH until FINNHUB_API_KEY is set — and `statement` names that
variable rather than letting two Yahoo endpoints agreeing look like confirmation.

Tolerances are per asset class because a normal spread differs by class: a
crypto composite and a single venue's book legitimately differ by a few basis
points continuously, while two equity feeds quoting the same consolidated tape
should agree far more tightly.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .asset_class import classify

CROSS_VENDOR = "CROSS_VENDOR"
CROSS_PATH = "CROSS_PATH"
SINGLE = "SINGLE"
DISAGREEMENT = "DISAGREEMENT"
UNAVAILABLE = "UNAVAILABLE"

# Max tolerated disagreement, in percent, before a price is refused.
TOLERANCE_PCT = {
    "CRYPTO": 1.00,    # composite vs single venue: bps of normal spread, plus
                       # genuine venue dispersion in thin conditions
    "EQUITY": 0.50,    # same consolidated tape; a wider gap is a real problem
    "ETF": 0.50,
    "FUND": 0.50,
    "INDEX": 0.75,     # index levels are computed, and vendors differ on timing
    "FX": 0.30,
    "FUTURE": 0.75,
    "UNKNOWN": 0.50,
}

# Which registered providers read a genuinely different UPSTREAM from which.
# Two providers in the same group are different code paths to one vendor, and
# agreement between them is CROSS_PATH, not CROSS_VENDOR.
VENDOR_GROUP = {
    "yfinance-rt": "yahoo",
    "yahoo-chart": "yahoo",
    "finnhub-quote": "finnhub",
    "crypto-spot": "crypto-native",
}

# Sources to poll per asset class, in preference order.
SOURCES_FOR_CLASS = {
    "CRYPTO": ("crypto-spot", "yfinance-rt"),
    "EQUITY": ("finnhub-quote", "yfinance-rt", "yahoo-chart"),
    "ETF": ("finnhub-quote", "yfinance-rt", "yahoo-chart"),
    "FUND": ("finnhub-quote", "yfinance-rt", "yahoo-chart"),
    "INDEX": ("yfinance-rt", "yahoo-chart"),
    "FX": ("yfinance-rt", "yahoo-chart"),
    "FUTURE": ("yfinance-rt", "yahoo-chart"),
    "UNKNOWN": ("yfinance-rt", "yahoo-chart"),
}

MAX_AGE_SEC = 15 * 60


def _fetch_one(provider: str, symbol: str) -> Optional[Dict[str, Any]]:
    """One provider's quote, or None. Never raises — a provider that is down
    must not take the consensus down with it."""
    from financial_data import gateway as G
    try:
        r = G.get("quote", symbol, provider=provider)
    except Exception:
        return None
    for d in (r.get("data") or []):
        try:
            v = float(d.get("value"))
        except (TypeError, ValueError):
            continue
        if v > 0:
            return {"provider": provider, "price": v,
                    "as_of": d.get("available_at"),
                    "vendor": VENDOR_GROUP.get(provider, provider),
                    "extra": d.get("extra") or {}}
    return None


def consensus(symbol: str, asset_class: Optional[str] = None,
              max_sources: int = 3) -> Dict[str, Any]:
    """Poll several providers for one symbol and grade the agreement.

    Returns `usable: False` on DISAGREEMENT even though prices were fetched.
    A caller that wants the raw readings anyway can read `quotes`.
    """
    sym = (symbol or "").upper().strip()
    cls = asset_class or classify(sym).get("asset_class", "UNKNOWN")
    tol = TOLERANCE_PCT.get(cls, TOLERANCE_PCT["UNKNOWN"])

    t0 = time.time()
    quotes: List[Dict[str, Any]] = []
    for prov in SOURCES_FOR_CLASS.get(cls, SOURCES_FOR_CLASS["UNKNOWN"]):
        q = _fetch_one(prov, sym)
        if q:
            quotes.append(q)
        if len(quotes) >= max_sources:
            break

    out: Dict[str, Any] = {
        "symbol": sym, "asset_class": cls, "tolerance_pct": tol,
        "quotes": quotes, "n_sources": len(quotes),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "price": None, "usable": False, "confirmation": UNAVAILABLE,
        "spread_pct": None, "statement": "",
    }

    if not quotes:
        out["statement"] = (f"No live price was available for {sym} from any "
                            f"registered source, so nothing real-time can be "
                            f"said about it.")
        return out

    prices = [q["price"] for q in quotes]
    lo, hi = min(prices), max(prices)
    spread = ((hi / lo - 1.0) * 100.0) if lo > 0 else 0.0
    out["spread_pct"] = round(spread, 4)
    # The best-reliability source leads; consensus never averages across
    # vendors, because a mean of a good price and a bad print is a third
    # number that no venue ever traded at.
    lead = quotes[0]
    vendors = {q["vendor"] for q in quotes}

    if len(quotes) == 1:
        out.update({"price": lead["price"], "usable": True,
                    "confirmation": SINGLE})
        missing = ("FINNHUB_API_KEY" if cls in ("EQUITY", "ETF", "FUND")
                   else None)
        out["statement"] = (
            f"{sym} is {lead['price']:,.2f} from {lead['provider']}, "
            f"uncorroborated — only one source answered."
            + (f" A second, independent equity vendor would require {missing}."
               if missing else ""))
        return out

    if spread > tol:
        out.update({"price": None, "usable": False,
                    "confirmation": DISAGREEMENT})
        detail = ", ".join(f"{q['provider']} {q['price']:,.2f}" for q in quotes)
        out["statement"] = (
            f"Sources disagree on {sym} by {spread:.2f}%, beyond the {tol:.2f}% "
            f"tolerance for {cls} ({detail}). No live price is reported: one of "
            f"these is likely a bad print, and predicting on either would be "
            f"a confident guess about which.")
        return out

    if len(vendors) > 1:
        out.update({"price": lead["price"], "usable": True,
                    "confirmation": CROSS_VENDOR})
        out["statement"] = (
            f"{sym} is {lead['price']:,.2f}, confirmed across {len(vendors)} "
            f"independent vendors agreeing within {spread:.2f}%.")
        return out

    out.update({"price": lead["price"], "usable": True,
                "confirmation": CROSS_PATH})
    missing = ("FINNHUB_API_KEY" if cls in ("EQUITY", "ETF", "FUND") else None)
    out["statement"] = (
        f"{sym} is {lead['price']:,.2f}. Two code paths to the same vendor "
        f"({lead['vendor']}) agree within {spread:.2f}%, which rules out a "
        f"stale cache but not a vendor-wide bad print."
        + (f" Independent confirmation would require {missing}." if missing else ""))
    return out


def price(symbol: str, asset_class: Optional[str] = None) -> Optional[float]:
    """The usable live price, or None. The deliberately blunt accessor for
    callers that cannot act on a status anyway — None on DISAGREEMENT."""
    c = consensus(symbol, asset_class)
    return c["price"] if c["usable"] else None
