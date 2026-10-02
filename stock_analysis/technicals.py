"""
Price context, tied to the filing calendar.

Descriptive, not predictive. Trend, relative strength, volatility and drawdown
describe where the price is; the earnings-reaction table describes how the
market has answered each results release. The desk's own measurements found
no out-of-sample edge in its algorithmic price signals (backtest/algo_legs.py,
49,880 observations): nothing here is offered as a forecast, and the scoring
layer (stock_analysis/scoring.py) does not read it.

Earnings reactions are measured at the 8-K Item 2.02 ("Results of Operations")
filing — the earnings release — not the 10-Q, which usually follows days
later. Each reaction is the stock's move from the close before the release to
the close the trading day after (a release after the bell is priced the next
morning), minus the market's (SPY) move over the same days; the drift is the
same comparison over the following twenty trading days.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

TRADING_DAYS = 252
BENCHMARK = "SPY"

# SIC ranges -> the SPDR sector fund that is the closest public benchmark.
# Approximate by construction: SIC predates the GICS sectors the funds follow.
_SECTOR_ETF = [
    ((3570, 3579), "XLK"), ((3600, 3699), "XLK"), ((7370, 7379), "XLK"), ((3820, 3829), "XLK"),
    ((2830, 2836), "XLV"), ((3840, 3851), "XLV"), ((8000, 8099), "XLV"), ((6320, 6324), "XLV"),
    ((6000, 6411), "XLF"), ((6700, 6797), "XLF"), ((6798, 6798), "XLRE"), ((6500, 6553), "XLRE"),
    ((1300, 1389), "XLE"), ((2900, 2999), "XLE"), ((4900, 4949), "XLU"),
    ((4800, 4899), "XLC"), ((7810, 7849), "XLC"), ((2700, 2799), "XLC"),
    ((2000, 2099), "XLP"), ((2100, 2199), "XLP"), ((5400, 5499), "XLP"), ((2840, 2844), "XLP"),
    ((3710, 3716), "XLY"), ((5000, 5999), "XLY"), ((7000, 7099), "XLY"), ((5800, 5899), "XLY"),
    ((1000, 1499), "XLB"), ((2600, 2699), "XLB"), ((2800, 2829), "XLB"), ((3300, 3399), "XLB"),
    ((3400, 3569), "XLI"), ((3700, 3799), "XLI"), ((4000, 4799), "XLI"), ((1500, 1799), "XLI"),
]


def sector_etf(sic: Optional[str]) -> Optional[str]:
    try:
        n = int(sic)
    except (TypeError, ValueError):
        return None
    for (lo, hi), etf in _SECTOR_ETF:
        if lo <= n <= hi:
            return etf
    return None


def _ret(close, days: int) -> Optional[float]:
    if len(close) <= days:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - days] - 1)


def price_context(df, bench=None, sector=None) -> Dict[str, Any]:
    """Trend, returns, volatility and drawdown from a close series. Pure."""
    close = df["Close"].dropna()
    if len(close) < 60:
        return {"available": False, "reason": "fewer than 60 trading days of prices"}
    px = float(close.iloc[-1])
    sma50 = float(close.tail(50).mean())
    sma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
    hi52, lo52 = float(close.tail(TRADING_DAYS).max()), float(close.tail(TRADING_DAYS).min())
    rets = close.pct_change().dropna()
    vol20 = float(rets.tail(20).std() * math.sqrt(TRADING_DAYS))
    vol60 = float(rets.tail(60).std() * math.sqrt(TRADING_DAYS))
    yr = close.tail(TRADING_DAYS)
    dd = float((yr / yr.cummax() - 1).min())
    out = {
        "available": True, "price": px, "date": str(close.index[-1])[:10],
        "above_50d": px > sma50, "above_200d": None if sma200 is None else px > sma200,
        "sma50": round(sma50, 2), "sma200": None if sma200 is None else round(sma200, 2),
        "trend": ("uptrend" if sma200 and px > sma50 > sma200 else
                  "downtrend" if sma200 and px < sma50 < sma200 else "mixed"),
        "from_52w_high": round(px / hi52 - 1, 4), "from_52w_low": round(px / lo52 - 1, 4),
        "returns": {k: (None if v is None else round(v, 4)) for k, v in
                    (("1m", _ret(close, 21)), ("3m", _ret(close, 63)), ("6m", _ret(close, 126)),
                     ("12m", _ret(close, TRADING_DAYS)))},
        "volatility_20d": round(vol20, 4), "volatility_60d": round(vol60, 4),
        "max_drawdown_1y": round(dd, 4),
    }
    for name, b in (("vs_market", bench), ("vs_sector", sector)):
        if b is not None and not b.empty and len(b["Close"].dropna()) > TRADING_DAYS // 2:
            bc = b["Close"].dropna()
            rel = {}
            for k, d in (("3m", 63), ("12m", TRADING_DAYS)):
                a, c = _ret(close, d), _ret(bc, d)
                rel[k] = None if a is None or c is None else round(a - c, 4)
            out[name] = rel
    return out


def _idx_after(index, day: str, offset: int = 0) -> Optional[int]:
    import numpy as np
    pos = int(np.searchsorted(index.values, np.datetime64(day), side="left"))
    pos += offset
    return pos if 0 <= pos < len(index) else None


def earnings_reactions(df, bench, release_dates: List[str]) -> Dict[str, Any]:
    """Market-adjusted move around each results release and the drift after. Pure."""
    close = df["Close"].dropna()
    bclose = bench["Close"].dropna() if bench is not None and not bench.empty else None
    rows = []
    for day in sorted(set(release_dates)):
        i0 = _idx_after(close.index, day)          # release day (or next trading day)
        if i0 is None or i0 < 1 or i0 + 1 >= len(close):
            continue
        before, after = close.iloc[i0 - 1], close.iloc[i0 + 1]
        move = float(after / before - 1)
        bmove = None
        if bclose is not None:
            j0 = _idx_after(bclose.index, day)
            if j0 is not None and j0 >= 1 and j0 + 1 < len(bclose):
                bmove = float(bclose.iloc[j0 + 1] / bclose.iloc[j0 - 1] - 1)
        drift = None
        if i0 + 21 < len(close):
            d = float(close.iloc[i0 + 21] / close.iloc[i0 + 1] - 1)
            if bclose is not None and j0 is not None and j0 + 21 < len(bclose):
                d -= float(bclose.iloc[j0 + 21] / bclose.iloc[j0 + 1] - 1)
            drift = d
        rows.append({"release": day, "reaction": round(move - (bmove or 0.0), 4), "raw_move": round(move, 4),
                     "market_move": None if bmove is None else round(bmove, 4),
                     "drift_20d": None if drift is None else round(drift, 4)})
    rows.sort(key=lambda r: r["release"], reverse=True)
    if not rows:
        return {"available": False, "reason": "no earnings releases inside the price history"}
    reacts = [r["reaction"] for r in rows]
    drifts = [r["drift_20d"] for r in rows if r["drift_20d"] is not None]
    same_dir = [r for r in rows if r["drift_20d"] is not None and r["reaction"] * r["drift_20d"] > 0]
    return {"available": True, "releases": rows[:12], "n": len(rows),
            "avg_abs_reaction": round(sum(abs(x) for x in reacts) / len(reacts), 4),
            "share_positive": round(sum(1 for x in reacts if x > 0) / len(reacts), 2),
            "avg_drift_20d": None if not drifts else round(sum(drifts) / len(drifts), 4),
            "drift_continued_share": None if not drifts else round(len(same_dir) / len(drifts), 2),
            "method": "stock minus SPY, close before the release to the close the trading day after; drift = "
                      "the next 20 trading days, also net of SPY"}


def build_technicals(symbol: str, profile: Dict[str, Any], filings: Optional[List[Dict[str, Any]]] = None,
                     as_of: Optional[str] = None) -> Dict[str, Any]:
    from financial_data import gateway as gw
    period = "4y" if not as_of else "10y"
    try:
        df = gw.get_bars_df(symbol, period=period, as_of=as_of)
    except Exception as e:
        return {"available": False, "reason": f"no prices: {type(e).__name__}"}
    if df.empty:
        return {"available": False, "reason": "no price history"}
    bench = gw.get_bars_df(BENCHMARK, period=period, as_of=as_of)
    etf = sector_etf(profile.get("sic"))
    sect = gw.get_bars_df(etf, period=period, as_of=as_of) if etf else None
    ctx = price_context(df, bench, sect)
    ctx["sector_benchmark"] = etf
    releases = [f["filed"] for f in (filings or []) if f["form"].startswith("8-K")
                and "2.02" in (f.get("items") or "")]
    ctx["earnings_reactions"] = earnings_reactions(df, bench, releases)
    ctx["note"] = ("Descriptive price context. The desk's own tests found no out-of-sample edge in its "
                   "algorithmic price signals; nothing here is a forecast and the score does not use it.")
    try:
        from tools.market_data import compute_indicators, compute_signal_summary
        ind = compute_indicators(df.tail(400))
        ctx["desk_technical_score"] = compute_signal_summary(ind).get("score")
    except Exception:
        ctx["desk_technical_score"] = None
    return ctx
