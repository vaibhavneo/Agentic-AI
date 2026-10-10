"""Bars from Yahoo's chart API (keyless), cached on disk.

    daily(sym, years=5)     -> DataFrame[open, high, low, close, adjclose, volume] indexed by date
    intraday(sym, days=60)  -> DataFrame[open, high, low, close, volume] of 5-minute bars, New York time

Cache: data/quant_cache/. Daily bars are reused for 6 hours, intraday bars for
2 minutes while the US market is open and until the next open otherwise. A
fetch that fails falls back to the last cached copy and says so in .attrs.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "quant_cache"
UA = "live-knowledge/1.0"        # the chart API answers this; browser/default agents get 429


def _get(url: str, timeout: float = 12.0) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
        return json.loads(r.read())


def _market_open() -> bool:
    try:
        from mas.converse.live_feed import us_market_open
        return us_market_open()
    except Exception:
        return False


def _fetch(sym: str, rng: str, interval: str, ttl_s: float, http: Optional[Callable] = None) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{sym.replace('^', '_').replace('/', '_')}_{interval}_{rng}.json"
    payload, stale = None, False
    if path.exists() and time.time() - path.stat().st_mtime < ttl_s:
        payload = json.loads(path.read_text())
    else:
        try:
            payload = (http or _get)("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym)
                                     + "?" + urllib.parse.urlencode({"range": rng, "interval": interval,
                                                                     "events": "div,splits"}))
            path.write_text(json.dumps(payload))
        except Exception:
            if path.exists():
                payload, stale = json.loads(path.read_text()), True
            else:
                raise
    res = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise ValueError(f"no bars for {sym}")
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"open": q.get("open"), "high": q.get("high"), "low": q.get("low"), "close": q.get("close"),
                       "volume": q.get("volume")},
                      index=pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("America/New_York"))
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    if adj:
        df["adjclose"] = adj
    df = df.dropna(subset=["close"])
    df.attrs.update(symbol=sym, source="Yahoo Finance chart API", stale=stale,
                    as_of=str(df.index[-1]) if len(df) else None, currency=res.get("meta", {}).get("currency"))
    return df


def daily(sym: str, years: int = 5, http: Optional[Callable] = None) -> pd.DataFrame:
    df = _fetch(sym.upper(), f"{years}y", "1d", 6 * 3600, http)
    df.index = df.index.normalize().tz_localize(None)
    df = df[~df.index.duplicated(keep="last")]
    if "adjclose" not in df:
        df["adjclose"] = df["close"]
    return df


def intraday(sym: str, days: int = 60, http: Optional[Callable] = None) -> pd.DataFrame:
    ttl = 120 if _market_open() else 6 * 3600
    return _fetch(sym.upper(), f"{min(days, 60)}d", "5m", ttl, http)


def returns(symbols, years: int = 3, http: Optional[Callable] = None) -> pd.DataFrame:
    """Daily simple returns of adjusted closes, aligned on common dates."""
    frames = {}
    for s in symbols:
        try:
            frames[s.upper()] = daily(s, years, http)["adjclose"]
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index().pct_change().dropna(how="all").dropna()
