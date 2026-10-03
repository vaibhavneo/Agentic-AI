"""
The market side of valuation: price, share count, currency, depositary ratio.

Everything a multiple needs that the financial statements do not carry, each
with where it came from:

  price        the close on or before `as_of`, through the gateway's bars path
  shares       the latest quarter's weighted DILUTED share count from the
               company's own filing — counts every share class (a cover-page
               count is per class: Alphabet files three), and matches EPS
  currency     statements stay in the reporting currency; multiples convert at
               the FRED daily rate on or before `as_of`, named
  ADS ratio    a foreign company's U.S. listing is usually a depositary share
               that represents several ordinary shares. The 20-F cover page
               states the ratio ("each representing five common shares");
               it is read from there. When the cover doesn't state one, market
               multiples are UNAVAILABLE rather than computed on a guess.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# FRED daily FX series: currency -> (series, quoted as units-per-USD?)
FX_SERIES = {
    "TWD": ("DEXTAUS", True), "JPY": ("DEXJPUS", True), "CNY": ("DEXCHUS", True), "KRW": ("DEXKOUS", True),
    "INR": ("DEXINUS", True), "HKD": ("DEXHKUS", True), "CAD": ("DEXCAUS", True), "CHF": ("DEXSZUS", True),
    "SEK": ("DEXSDUS", True), "NOK": ("DEXNOUS", True), "DKK": ("DEXDNUS", True), "SGD": ("DEXSIUS", True),
    "MXN": ("DEXMXUS", True), "BRL": ("DEXBZUS", True), "ZAR": ("DEXSFUS", True), "THB": ("DEXTHUS", True),
    "EUR": ("DEXUSEU", False), "GBP": ("DEXUSUK", False), "AUD": ("DEXUSAL", False), "NZD": ("DEXUSNZ", False),
}

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40,
          "fifty": 50, "hundred": 100, "one hundred": 100, "half": 0.5, "one-half": 0.5, "one-third": 1 / 3,
          "one-fourth": 0.25, "one-fifth": 0.2, "one-tenth": 0.1}


def price_on(symbol: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    from financial_data import gateway as gw
    try:
        if as_of:
            # A window AROUND the date: "6y back from today" ends before an
            # as_of of 2019 and returns nothing.
            from datetime import date, timedelta
            d = date.fromisoformat(as_of[:10])
            df = gw.get_bars_df(symbol, start=(d - timedelta(days=20)).isoformat(),
                                end=(d + timedelta(days=1)).isoformat(), as_of=as_of,
                                price_basis="split_adjusted_only")
        else:
            df = gw.get_bars_df(symbol, period="1mo")
    except Exception as e:
        return {"available": False, "reason": f"no price: {type(e).__name__}"}
    if df.empty:
        return {"available": False, "reason": "no price history for this symbol"}
    date_ = str(df.index[-1])[:10]
    px = float(df["Close"].iloc[-1])
    factor = split_factor_after(symbol, date_) if as_of else 1.0
    return {"available": True, "price": px * factor, "date": date_,
            "provider": df.attrs.get("provider"), "as_of_honored": df.attrs.get("as_of_honored"),
            "basis": "as traded (split-adjusted close × later splits)" if as_of else "latest close",
            "split_factor": factor}


def split_factor_after(symbol: str, day: str) -> float:
    """Product of every split after `day`: turns a split-adjusted historical
    close back into the price that traded then (Nvidia, Feb 2020: $6.81 × 4 × 10)."""
    from financial_data import gateway as gw
    try:
        res = gw.get("corporate_actions", symbol)
    except Exception:
        return 1.0
    f = 1.0
    for d in res["data"]:
        if d.get("concept") == "split" and str(d["available_at"])[:10] > day[:10] and d["value"]:
            f *= float(d["value"])
    return f


def splits(symbol: str) -> List[Tuple[str, float]]:
    from financial_data import gateway as gw
    try:
        res = gw.get("corporate_actions", symbol)
    except Exception:
        return []
    return [(str(d["available_at"])[:10], float(d["value"])) for d in res["data"]
            if d.get("concept") == "split" and d["value"]]


def price_history(symbol: str, years: int = 7, as_of: Optional[str] = None, as_traded: bool = False,
                  split_only: bool = False):
    """Closes. Default: fully adjusted (for returns). split_only=True: not
    dividend-adjusted, on TODAY's split basis. as_traded=True: the price that
    actually traded each day (splits undone too)."""
    from financial_data import gateway as gw
    try:
        df = gw.get_bars_df(symbol, period=f"{years + (0 if not as_of else 6)}y", as_of=as_of,
                            **({"price_basis": "split_adjusted_only"} if (as_traded or split_only) else {}))
        if as_traded and not df.empty:
            res = gw.get("corporate_actions", symbol)
            for d in res["data"]:
                if d.get("concept") == "split" and d["value"]:
                    cut = str(d["available_at"])[:10]
                    df.loc[df.index < cut, "Close"] = df.loc[df.index < cut, "Close"] * float(d["value"])
        return df
    except Exception:
        import pandas as pd
        return pd.DataFrame()


def fx_to_usd(currency: Optional[str], on: Optional[str] = None) -> Dict[str, Any]:
    """USD per one unit of `currency`, on or before `on`."""
    if not currency or currency == "USD":
        return {"available": True, "rate": 1.0, "series": None, "date": on}
    spec = FX_SERIES.get(currency)
    if not spec:
        return {"available": False, "reason": f"no FRED daily series for {currency}"}
    from financial_data import gateway as gw
    try:
        res = gw.get("macro", spec[0])
    except Exception as e:
        return {"available": False, "reason": f"FRED unavailable: {type(e).__name__}"}
    pts = [d for d in res["data"] if (not on or str(d["available_at"])[:10] <= on[:10])]
    pts = [d for d in pts if isinstance(d["value"], (int, float)) and d["value"]]
    if not pts:
        return {"available": False, "reason": f"no {spec[0]} observation on or before {on}"}
    last = pts[-1]
    rate = (1.0 / float(last["value"])) if spec[1] else float(last["value"])
    return {"available": True, "rate": rate, "series": spec[0], "date": str(last["available_at"])[:10],
            "quote": float(last["value"]), "note": "FRED H.10 noon buying rate; current vintage"}


_ADS = r"(?:American Depositary Shares?|ADSs?|ADS)"
_RATIO_PATTERNS = [
    # "American Depositary Shares, each representing eight Ordinary Shares" (BABA, SAP)
    _ADS + r"[^.]{0,80}?\beach\s+(?:of which\s+)?(?:ADS\s+)?(?:representing|represents|evidencing)\s+"
           r"(?:the right to receive\s+)?([\w\-]+)\s*(?:\(\d+(?:\.\d+)?\)\s*)?(?:of\s+(?:our|the)\s+)?"
           r"(?:ordinary|common|equity)?\s*shares?",
    # "Each American Depositary Share representing ten shares of the registrant's Common Stock" (TM)
    r"\beach\s+" + _ADS + r"\s+(?:represents|representing|evidences)\s+(?:the right to receive\s+)?"
    r"([\w\-]+)\s*(?:\(\d+(?:\.\d+)?\)\s*)?(?:of\s+(?:our|the)\s+)?(?:ordinary|common)?\s*shares?",
    # "one ADS represents five common shares" / "each ADS represents 5 shares" (TSMC, deeper in the 20-F)
    r"\b(?:one|1)\s+" + _ADS + r"\s+(?:represents|representing|is equivalent to)\s+([\w\-]+)\s+"
    r"(?:ordinary|common)?\s*shares?",
]


def _ratio_word(word: str) -> Optional[float]:
    w = word.lower().strip()
    if w in _WORDS:
        return float(_WORDS[w])
    try:
        return float(w)
    except ValueError:
        return None


def adr_ratio(text: str) -> Optional[Dict[str, Any]]:
    """Ordinary shares per U.S.-listed depositary share, as the 20-F states it.
    The cover page usually says it; some (TSMC) only say it further in, so the
    whole report is read and the ratio stated most often wins."""
    flat = re.sub(r"\s+", " ", text)
    found: Dict[float, str] = {}
    counts: Dict[float, int] = {}
    for pat in _RATIO_PATTERNS:
        for m in re.finditer(pat, flat, re.I):
            n = _ratio_word(m.group(1))
            if n and 0.01 <= n <= 1000:
                counts[n] = counts.get(n, 0) + 1
                found.setdefault(n, flat[max(0, m.start() - 20):m.end() + 20].strip())
    if counts:
        best = max(counts, key=lambda k: counts[k])
        return {"ratio": best, "quote": found[best], "mentions": counts[best],
                "source": "20-F text" + ("" if len(counts) == 1 else f" (other ratios also stated: "
                                         f"{sorted(k for k in counts if k != best)})")}
    head = flat[:60000]
    # Ordinary shares listed directly (ASML).
    if re.search(r"(Ordinary|Common) [Ss]hares[^.]{0,80}(Nasdaq|New York Stock Exchange)", head) and \
            not re.search(r"American Depositary", head, re.I):
        return {"ratio": 1.0, "quote": "ordinary shares listed directly in the U.S.", "source": "20-F cover page"}
    return None


# Exxon reports one EPS "basic and assuming dilution" and has tagged no
# diluted share count since 2013; its basic count IS its diluted count.
SHARE_SOURCES = (("shares_diluted", "weighted diluted shares"),
                 ("shares_basic", "weighted basic shares (the filing reports no separate diluted count)"),
                 ("shares_outstanding_cover", "shares outstanding on the filing's cover"))


def share_count(blk: Dict[str, Any]) -> Optional[tuple]:
    """(shares, concept, label) from one statement block, best source first."""
    from .statements import value
    for concept, label in SHARE_SOURCES:
        v = value(blk, concept)
        if v:
            return v, concept, label
    return None


def market_inputs(symbol: str, statements: Dict[str, Any], as_of: Optional[str] = None,
                  annual_text: Optional[str] = None, price: Optional[float] = None) -> Dict[str, Any]:
    """Market cap and EV in USD, with every input and its source. `price`
    lets a caller that already holds the quote (the live pillar) skip a fetch."""
    from .statements import value
    out: Dict[str, Any] = {"available": False, "warnings": []}
    if price:
        from datetime import date
        px = {"available": True, "price": float(price), "date": (as_of or date.today().isoformat())[:10],
              "provider": "caller"}
    else:
        px = price_on(symbol, as_of)
    if not px.get("available"):
        out["reason"] = px.get("reason")
        return out
    filer = statements.get("filer") or {}
    qs = statements.get("quarters") or []
    shares, shares_src = None, None
    for blk in qs[:2] + statements.get("annual", [])[:1]:
        found = share_count(blk)
        if found:
            shares, concept, label = found
            shares_src = f"{label}, {blk['label']} ({blk['values'][concept].get('accession')})"
            break
    if not shares:
        out["reason"] = "no share count in the filings"
        return out
    ratio = 1.0
    ratio_src = None
    if filer.get("is_foreign"):
        r = adr_ratio(annual_text or "")
        if not r:
            out["reason"] = ("the 20-F cover does not state how many ordinary shares one U.S.-listed share "
                             "represents — market multiples not computed")
            return out
        ratio, ratio_src = r["ratio"], r
    fx = fx_to_usd(filer.get("currency"), as_of or px["date"])
    if not fx.get("available"):
        out["reason"] = f"currency conversion unavailable: {fx.get('reason')}"
        return out
    t = statements.get("ttm") or {}
    usd = fx["rate"]
    market_cap = px["price"] * shares / ratio
    debt = ((value(t, "long_term_debt") or 0.0) + (value(t, "short_term_debt") or 0.0)) * usd
    cash = ((value(t, "cash") or 0.0) + (value(t, "short_term_investments") or 0.0)) * usd
    if value(t, "long_term_debt") is None and value(t, "short_term_debt") is None:
        out["warnings"].append("no debt reported in the filings: enterprise value assumes zero debt")
    out.update({
        "available": True, "price": px["price"], "price_date": px["date"], "price_provider": px["provider"],
        "shares": shares, "shares_source": shares_src, "ads_ratio": ratio, "ads_ratio_source": ratio_src,
        "currency": filer.get("currency"), "fx": fx,
        "market_cap_usd": market_cap, "debt_usd": debt, "cash_usd": cash,
        "enterprise_value_usd": market_cap + debt - cash,
    })
    return out
