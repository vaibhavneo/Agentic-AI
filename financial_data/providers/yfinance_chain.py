"""
FIL provider — listed option chains with IMPLIED volatility. Keyless.

This exists because the desk was pricing options from the wrong input and its
own registry said so: `derivatives` carries the note that "realized vol is the
wrong input for an option price", and reliability 0.55 to match. Measured on
IONQ on 2026-09-26 the cost of that was specific:

    engine, realized 30-bar vol : 70.83%
    market, implied vol         : 79.19%
    gap                         : 8.36 vol points
    live vega                   : 0.068875 per share per vol point
    error                       : 8.36 x 0.068875 x 100 = $57.59 per contract
                                  on a $590 mark, i.e. 9.8% understated

A model has no way to find that number. It is what the market is charging, and
the only place to read it is the chain.

Two more things a realized number structurally cannot express, both of which
decide whether a structure is worth entering:

  THE SPREAD.  IONQ's 45-strike call quoted 5.75 / 6.05 — a 5.1% round trip that
  model pricing treats as zero. On a horizon where the whole edge is a few
  percent, a cost of five is not a detail.

  THE SKEW.  Calls implied 79.19% against puts at 78.34%. One volatility figure
  cannot hold two different prices for risk in two directions.

And it fixes a plain error: `expiry_date()` snaps to a Friday, so for IONQ it
produced 2026-11-13 — a date that is not an IONQ expiration at all. The real
chain runs 11-06 then 11-20 (monthlies). The desk was pricing a contract that
does not exist. Real expirations come from here now.

Keyless, via yfinance, which negotiates Yahoo's session crumb internally — the
raw endpoint returns "Invalid Crumb" without it. Cross-checked against an
independent broker feed on the same contract: bid, ask, open interest and volume
matched exactly; implied vol differed by 1.2 points, which is two different
solvers on the same quotes rather than a data disagreement.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..schemas import make_datum, make_source

KINDS = ("option_chain",)

# A contract needs some evidence of life before its implied vol means anything:
# an IV solved from a stale or one-sided quote is arithmetic on nothing.
MIN_OPEN_INTEREST = 1

# Half-width of the at-the-money strike band, as a fraction of the money.
# Proportional rather than absolute: 10% of a $45 name is $4.50, of a $450 name
# is $45, and a fixed dollar band would be the whole chain on one and a single
# strike on the other.
ATM_BAND_PCT = 0.10


class ProviderError(RuntimeError):
    pass


def _rows(df, kind: str) -> List[Dict[str, Any]]:
    out = []
    if df is None or len(df) == 0:
        return out
    for _, r in df.iterrows():
        try:
            strike = float(r["strike"])
            iv = r.get("impliedVolatility")
            iv = float(iv) if iv is not None else None
        except (TypeError, ValueError, KeyError):
            continue
        if strike <= 0:
            continue

        def _f(col):
            v = r.get(col)
            try:
                return float(v) if v is not None and v == v else None
            except (TypeError, ValueError):
                return None

        out.append({
            "type": kind, "strike": strike,
            "implied_volatility": iv,
            "bid": _f("bid"), "ask": _f("ask"), "last": _f("lastPrice"),
            "open_interest": _f("openInterest"), "volume": _f("volume"),
            "in_the_money": bool(r.get("inTheMoney")),
            "contract": r.get("contractSymbol"),
        })
    return out


def expirations(symbol: str) -> List[str]:
    """Real listed expirations. The reason expiry_date() must not guess."""
    import yfinance as yf
    try:
        return list(yf.Ticker(symbol.upper()).options or [])
    except Exception as e:
        raise ProviderError(f"could not list expirations: {type(e).__name__}") from e


def fetch(kind: str, symbols: List[str], start: Optional[str] = None,
          end: Optional[str] = None, as_of: Optional[str] = None,
          expiration: Optional[str] = None, reliability: float = 0.8,
          **kwargs: Any) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ProviderError(f"yfinance-chain does not serve kind {kind!r}")

    import yfinance as yf

    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if as_of:
        warnings.append("an option chain is a live snapshot; no free vendor "
                        "serves a historical one, so as_of_honored is False")

    for sym in symbols:
        s = sym.upper().strip()
        try:
            t = yf.Ticker(s)
            exps = list(t.options or [])
            if not exps:
                raise ProviderError("no listed expirations (the name may have "
                                    "no options market)")
            exp = expiration if expiration in exps else exps[0]
            ch = t.option_chain(exp)
            calls, puts = _rows(ch.calls, "call"), _rows(ch.puts, "put")
            if not calls and not puts:
                raise ProviderError(f"chain for {exp} returned no contracts")

            now = datetime.now(timezone.utc)
            data.append(make_datum(
                kind="option_chain",
                # The datum's VALUE is the at-the-money implied volatility,
                # because that is the single number a caller most often wants
                # and a dict with no scalar value cannot be compared or ranked.
                # The full chain rides in `extra`.
                value=_atm_iv(calls, puts),
                available_at=now,
                source=make_source(provider="yfinance-chain",
                                   document=f"{s}:{exp}",
                                   ref="option_chain.impliedVolatility"),
                symbol=s, concept="atm_implied_volatility", unit="fraction",
                confidence=reliability, status="actual",
                extra={"expiration": exp, "expirations": exps,
                       "calls": calls, "puts": puts,
                       "n_calls": len(calls), "n_puts": len(puts)}))
        except Exception as e:
            unavailable.append({"symbol": s, "kind": kind,
                                "reason": f"{type(e).__name__}: {e}"})
    return {"data": data, "unavailable": unavailable, "warnings": warnings}


def _atm_iv(calls: List[Dict[str, Any]],
            puts: List[Dict[str, Any]]) -> Optional[float]:
    """At-the-money implied vol, as the mean of the nearest call and put.

    The nearest-to-the-money contract is used rather than an average across the
    chain: deep wings carry their own skew and averaging them produces a number
    that describes no contract anybody would trade. Call and put are averaged
    because the two differ by the skew, and taking only one would import a
    directional bias into a volatility figure.
    """
    live = [c for c in calls + puts
            if c.get("implied_volatility") and (c.get("open_interest") or 0)
            >= MIN_OPEN_INTEREST]
    if not live:
        return None
    itm = [c for c in live if c["in_the_money"]]
    otm = [c for c in live if not c["in_the_money"]]
    if not itm or not otm:
        return round(sum(c["implied_volatility"] for c in live) / len(live), 6)

    # The money sits between the highest ITM strike and the lowest OTM strike.
    boundary = (max(c["strike"] for c in itm) + min(c["strike"] for c in otm)) / 2

    # Select by a STRIKE BAND, not a fixed count. A fixed "nearest N" is fragile
    # on a thin chain: with only four live contracts, nearest-4 is the entire
    # chain including both wings, and a fixture with a 200-strike at 190% vol
    # returned 1.23 where the money was near 0.51. A proportional band keeps the
    # wings out however many contracts the name lists.
    band = ATM_BAND_PCT * boundary
    near = [c for c in live if abs(c["strike"] - boundary) <= band]
    if not near:
        # Nothing inside the band (very wide strike spacing): fall back to the
        # single closest contract on each side rather than the whole chain.
        near = ([min(itm, key=lambda c: boundary - c["strike"])]
                + [min(otm, key=lambda c: c["strike"] - boundary)])
    return round(sum(c["implied_volatility"] for c in near) / len(near), 6)
