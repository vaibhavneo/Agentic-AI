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
from typing import Any, Dict, Optional

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
        df = gw.get_bars_df(symbol, period="1mo" if not as_of else "6y", as_of=as_of)
    except Exception as e:
        return {"available": False, "reason": f"no price: {type(e).__name__}"}
    if df.empty:
        return {"available": False, "reason": "no price history for this symbol"}
    return {"available": True, "price": float(df["Close"].iloc[-1]), "date": str(df.index[-1])[:10],
            "provider": df.attrs.get("provider"), "as_of_honored": df.attrs.get("as_of_honored")}


def price_history(symbol: str, years: int = 7, as_of: Optional[str] = None):
    from financial_data import gateway as gw
    try:
        return gw.get_bars_df(symbol, period=f"{years + (0 if not as_of else 6)}y", as_of=as_of)
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


def adr_ratio(text: str) -> Optional[Dict[str, Any]]:
    """Ordinary shares per U.S.-listed depositary share, as the 20-F cover states it."""
    head = re.sub(r"\s+", " ", text[:60000])
    m = re.search(r"American Depositary Shares?,?\s*(?:\(\"?ADSs?\"?\))?[^.]{0,60}?\beach\s+(?:ADS\s+)?"
                  r"(?:representing|represents|representing the right to receive|evidencing)\s+"
                  r"(?:the right to receive\s+)?([\w\-]+(?:\s+hundred)?)\s*(?:\(\d+(?:\.\d+)?\)\s*)?"
                  r"(?:of\s+(?:our|the)\s+)?(?:ordinary|common|equity)?\s*shares?", head, re.I)
    if m:
        word = m.group(1).lower()
        n = _WORDS.get(word)
        if n is None:
            try:
                n = float(word)
            except ValueError:
                n = None
        if n:
            return {"ratio": float(n), "quote": head[max(0, m.start() - 20):m.end() + 20].strip(),
                    "source": "20-F cover page"}
    # Ordinary shares listed directly (ASML, SAP on NYSE as ordinary/registry shares).
    if re.search(r"(Ordinary|Common) [Ss]hares[^.]{0,80}(Nasdaq|New York Stock Exchange)", head) and \
            not re.search(r"American Depositary", head, re.I):
        return {"ratio": 1.0, "quote": "ordinary shares listed directly in the U.S.", "source": "20-F cover page"}
    return None


def market_inputs(symbol: str, statements: Dict[str, Any], as_of: Optional[str] = None,
                  annual_text: Optional[str] = None) -> Dict[str, Any]:
    """Market cap and EV in USD, with every input and its source."""
    from .statements import value
    out: Dict[str, Any] = {"available": False, "warnings": []}
    px = price_on(symbol, as_of)
    if not px.get("available"):
        out["reason"] = px.get("reason")
        return out
    filer = statements.get("filer") or {}
    qs = statements.get("quarters") or []
    shares, shares_src = None, None
    for blk in qs[:2] + statements.get("annual", [])[:1]:
        v = value(blk, "shares_diluted")
        if v:
            shares, shares_src = v, f"weighted diluted shares, {blk['label']} ({blk['values']['shares_diluted'].get('accession')})"
            break
    if not shares:
        out["reason"] = "no diluted share count in the filings"
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
