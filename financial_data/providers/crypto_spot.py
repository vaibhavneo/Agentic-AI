"""
FIL provider — keyless crypto spot from Coinbase, with CoinGecko as fallback.

This is the one place in the registry where a genuine CROSS-VENDOR check is
available without an API key, which is why it is worth its own module rather
than a branch inside an equity provider. Coinbase and CoinGecko have different
upstreams and different methodologies (an exchange's own book versus a
volume-weighted cross-exchange composite), so when they disagree beyond a
tolerance, something is actually wrong with one of them.

That difference in methodology is also why a small spread is NORMAL here and
must not be reported as an anomaly: a single venue's last trade and a
cross-venue composite legitimately differ by a few basis points at all times.
`realtime.py` sets the crypto tolerance wider than the equity one for exactly
this reason.

Crypto trades 24/7, so unlike the equity providers there is no stale-weekend
case to reason about; an old timestamp here means a real outage.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..schemas import make_datum, make_source
from ._http import get_text

KINDS = ("quote",)

COINBASE = "https://api.coinbase.com/v2/prices/{pair}/spot"
COINGECKO = "https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies=usd"

# CoinGecko keys on slugs, not tickers. Only the majors are mapped: an unmapped
# symbol falls back to Coinbase alone rather than guessing a slug, because a
# wrong slug returns a confident price for the wrong asset.
GECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
    "ADA": "cardano", "DOGE": "dogecoin", "AVAX": "avalanche-2",
    "DOT": "polkadot", "LINK": "chainlink", "MATIC": "matic-network",
    "LTC": "litecoin", "BCH": "bitcoin-cash", "UNI": "uniswap",
    "ATOM": "cosmos", "XLM": "stellar", "ETC": "ethereum-classic",
}


class ProviderError(RuntimeError):
    pass


def _split(symbol: str) -> tuple:
    """`BTC-USD` / `BTCUSD` / `BTC` -> (BASE, QUOTE)."""
    s = (symbol or "").upper().strip()
    if "-" in s:
        base, _, quote = s.partition("-")
        return base, (quote or "USD")
    for q in ("USDT", "USDC", "USD"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)], q
    return s, "USD"


def _coinbase(base: str, quote: str) -> float:
    raw = json.loads(get_text(COINBASE.format(pair=f"{base}-{quote}"), timeout=10))
    amt = ((raw.get("data") or {}).get("amount"))
    if amt is None:
        raise ProviderError("coinbase returned no amount")
    return float(amt)


def _coingecko(base: str) -> float:
    slug = GECKO_IDS.get(base)
    if not slug:
        raise ProviderError(f"no coingecko slug mapped for {base!r}")
    raw = json.loads(get_text(COINGECKO.format(id=slug), timeout=10))
    usd = ((raw.get(slug) or {}).get("usd"))
    if usd is None:
        raise ProviderError("coingecko returned no usd price")
    return float(usd)


def fetch(kind: str, symbols: List[str], start: Optional[str] = None,
          end: Optional[str] = None, as_of: Optional[str] = None,
          reliability: float = 0.85, **kwargs: Any) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ProviderError(f"crypto-spot does not serve kind {kind!r}")

    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if as_of:
        warnings.append("a spot price cannot be served as-of a past instant; "
                        "as_of_honored is False")

    for sym in symbols:
        base, quote = _split(sym)
        price = None
        venue = None
        reasons = []
        for name, fn in (("coinbase", lambda: _coinbase(base, quote)),
                         ("coingecko", lambda: _coingecko(base))):
            try:
                p = fn()
                if p > 0:
                    price, venue = p, name
                    break
                reasons.append(f"{name}: implausible price {p!r}")
            except Exception as e:
                reasons.append(f"{name}: {type(e).__name__}: {e}")

        if price is None:
            unavailable.append({"symbol": sym.upper(), "kind": kind,
                                "reason": "; ".join(reasons)})
            continue

        data.append(make_datum(
            kind="quote", value=price, available_at=datetime.now(timezone.utc),
            source=make_source(provider="crypto-spot",
                               document=f"{base}-{quote}:spot", ref=f"{venue}.spot"),
            symbol=sym.upper(), concept="last_trade", unit=quote,
            confidence=reliability, status="actual",
            extra={"interval": None, "venue": venue, "base": base, "quote": quote,
                   "fallbacks_tried": reasons or None}))
    return {"data": data, "unavailable": unavailable, "warnings": warnings}


def cross_check(symbol: str) -> Dict[str, Any]:
    """Both vendors at once — what `realtime.consensus()` reads for crypto.

    Kept here rather than in realtime.py because the venue pair and the reason
    their spread is normally non-zero are facts about THIS provider.
    """
    base, quote = _split(symbol)
    out: Dict[str, Any] = {"symbol": symbol.upper(), "prices": {}, "errors": {}}
    for name, fn in (("coinbase", lambda: _coinbase(base, quote)),
                     ("coingecko", lambda: _coingecko(base))):
        try:
            out["prices"][name] = fn()
        except Exception as e:
            out["errors"][name] = f"{type(e).__name__}: {e}"
    return out
