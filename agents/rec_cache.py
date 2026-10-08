"""
A short-lived cache for /api/recommendation — the deterministic 7-pillar call.

The call is pure arithmetic over daily bars, filings and social counts, so the
same ticker asked twice gives the same answer until the inputs move. On Render's
free tier (0.1 CPU) one build takes many times the ~5 s it takes on the Mac, and
OptionsPilot and repeat visitors ask for the same names.

    market hours (Mon-Fri 09:30-16:00 New York)   15 minutes — the last bar moves
    otherwise                                      until the next 09:30 open

A hit also skips re-freezing a duplicate snapshot: /api/recommendation froze one
on EVERY call, which is why the hosted desk had to run as a secondary ledger.
`refresh` bypasses the cache. Holidays are treated as trading days (a 15-minute
TTL on a holiday is merely conservative).
"""
from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    NY = None

MARKET_TTL_S = 15 * 60
MAX_ENTRIES = 300
_lock = threading.Lock()
_store: Dict[Tuple[str, str], Tuple[float, float, Dict[str, Any]]] = {}   # key -> (stored, expires, rec)


def _now_ny(now: Optional[datetime] = None) -> datetime:
    if now is not None:
        return now
    return datetime.now(NY) if NY else datetime.utcnow() - timedelta(hours=4)


def ttl_seconds(now: Optional[datetime] = None) -> float:
    t = _now_ny(now)
    open_ = t.replace(hour=9, minute=30, second=0, microsecond=0)
    close = t.replace(hour=16, minute=0, second=0, microsecond=0)
    if t.weekday() < 5 and open_ <= t < close:
        return float(MARKET_TTL_S)
    nxt = open_ if (t.weekday() < 5 and t < open_) else open_ + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return max(60.0, (nxt - t).total_seconds())


def get(ticker: str, period: str) -> Optional[Dict[str, Any]]:
    key = (ticker.upper(), period)
    with _lock:
        hit = _store.get(key)
        if not hit:
            return None
        stored, expires, rec = hit
        if time.time() >= expires:
            _store.pop(key, None)
            return None
    out = copy.deepcopy(rec)
    out["cache"] = {"hit": True, "age_s": round(time.time() - stored, 1),
                    "expires_in_s": round(expires - time.time(), 1)}
    return out


def put(ticker: str, period: str, rec: Dict[str, Any], now: Optional[datetime] = None) -> None:
    if not isinstance(rec, dict) or rec.get("error"):
        return                                      # never cache a failure
    t = time.time()
    with _lock:
        if len(_store) >= MAX_ENTRIES:
            oldest = min(_store, key=lambda k: _store[k][0])
            _store.pop(oldest, None)
        _store[(ticker.upper(), period)] = (t, t + ttl_seconds(now), copy.deepcopy(rec))


def clear() -> None:
    with _lock:
        _store.clear()
