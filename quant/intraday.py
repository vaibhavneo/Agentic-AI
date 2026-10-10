"""Intraday signals on 5-minute bars: scanner, backtest and a paper journal.

Rules (one signal per rule and direction per symbol per day, each with levels):

    orb_long / orb_short      a close beyond the 30-minute opening range after 10:00, on above-normal volume;
                              stop: the other side of the range
    vwap_reclaim / vwap_loss  a close back across VWAP after 3+ bars on the other side, on above-normal volume;
                              stop: the last 6 bars' extreme
    rsi_bounce / rsi_fade     RSI(14) crossing back up through 30 / down through 70; stop: the last 6 bars' extreme
    gap_and_go                opening gap of 2%+ whose first 15 minutes close above the open; stop: the day's low

Every signal: entry (the signal bar's close), stop, target = entry ± 2 × risk.
Relative volume (rvol): the bar's volume over the average volume of the same
5-minute slot in the prior 20 sessions.

Backtest: each rule replayed over the cached 60 days of bars; a trade is
graded on the same day's later bars — stop first if both are touched in one
bar (conservative), otherwise target, otherwise the close. Results in R
(multiples of the risk taken).

Signals are research, paper-tracked in data/quant_journal.db. Nothing here
places an order.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from quant import prices as P

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "data" / "quant_journal.db"
RULES = ("orb_long", "orb_short", "vwap_reclaim", "vwap_loss", "rsi_bounce", "rsi_fade", "gap_and_go")
LONG = {"orb_long", "vwap_reclaim", "rsi_bounce", "gap_and_go"}
R_TARGET = 2.0
MIN_RVOL = 1.2


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _rsi_by_day(close: np.ndarray, day_start: np.ndarray, n: int = 14) -> np.ndarray:
    """Wilder RSI(n) that restarts every session — one pass, no groupby."""
    out = np.full(len(close), np.nan)
    a = 1.0 / n
    up = dn = 0.0
    for i in range(len(close)):
        if day_start[i]:
            up = dn = 0.0
            seeded = False
            continue
        d = close[i] - close[i - 1]
        g, l = (d, 0.0) if d > 0 else (0.0, -d)
        if not seeded:
            up, dn, seeded = g, l, True
        else:
            up, dn = up + a * (g - up), dn + a * (l - dn)
        out[i] = np.nan if dn == 0 else 100 - 100 / (1 + up / dn)     # no down move yet: undefined, as before
    return out


def prepare(bars: pd.DataFrame) -> pd.DataFrame:
    """Regular-session bars with per-day VWAP, RSI, slot and relative volume."""
    df = bars.copy()
    df = df[(df.index.time >= dtime(9, 30)) & (df.index.time < dtime(16, 0))]
    df["day"] = df.index.date
    # Minutes after midnight, not strftime: formatting tz-aware stamps costs ~0.3 s a symbol under gunicorn.
    df["slot"] = df.index.hour * 60 + df.index.minute
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (tp * df["volume"]).groupby(df["day"]).cumsum() / df["volume"].groupby(df["day"]).cumsum()
    day = df["day"].to_numpy()
    start = np.r_[True, day[1:] != day[:-1]] if len(day) else np.array([], bool)
    df["rsi"] = _rsi_by_day(df["close"].to_numpy(float), start)
    # Relative volume: this bar over the same 5-minute slot's average in the prior 20 sessions,
    # from a session x slot matrix rather than 78 grouped rolling windows.
    vol = df.pivot_table(index="day", columns="slot", values="volume", aggfunc="last")
    avg = vol.shift(1).rolling(20, min_periods=5).mean()
    stacked = avg.stack()
    keys = pd.MultiIndex.from_arrays([df["day"], df["slot"]])
    df["rvol"] = df["volume"].to_numpy() / stacked.reindex(keys).to_numpy()
    return df


def _signals_for_day(d: pd.DataFrame, prev_close: Optional[float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if len(d) < 8:
        return out
    fired = set()
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    vw, rsi = d["vwap"].to_numpy(float), d["rsi"].to_numpy(float)
    rvol = np.nan_to_num(d["rvol"].to_numpy(float), nan=0.0)
    mins = d.index.hour * 60 + d.index.minute
    T10, T1530 = 10 * 60, 15 * 60 + 30

    def emit(i, rule, stop):
        entry = float(c[i])
        risk = abs(entry - stop)
        if rule in fired or risk <= 0 or risk / entry < 0.001:
            return
        fired.add(rule)
        long = rule in LONG
        out.append({"rule": rule, "side": "long" if long else "short", "i": i, "ts": d.index[i],
                    "entry": round(entry, 4), "stop": round(float(stop), 4),
                    "target": round(entry + (R_TARGET * risk if long else -R_TARGET * risk), 4),
                    "rvol": round(float(rvol[i]), 2) if rvol[i] else None})

    orh, orl = float(h[:6].max()), float(l[:6].min())
    below = above = 0
    for i in range(1, len(d)):
        t = mins[i]
        lo6, hi6 = float(l[max(0, i - 5):i + 1].min()), float(h[max(0, i - 5):i + 1].max())
        if i >= 6 and T10 <= t < T1530:
            if c[i] > orh >= c[i - 1] and rvol[i] >= MIN_RVOL:
                emit(i, "orb_long", orl)
            if c[i] < orl <= c[i - 1] and rvol[i] >= MIN_RVOL:
                emit(i, "orb_short", orh)
        if t < T1530:
            below = below + 1 if c[i - 1] < vw[i - 1] else 0
            above = above + 1 if c[i - 1] > vw[i - 1] else 0
            if below >= 3 and c[i] > vw[i] and rvol[i] >= MIN_RVOL:
                emit(i, "vwap_reclaim", lo6)
            if above >= 3 and c[i] < vw[i] and rvol[i] >= MIN_RVOL:
                emit(i, "vwap_loss", hi6)
            if not (np.isnan(rsi[i - 1]) or np.isnan(rsi[i])):
                if rsi[i - 1] < 30 <= rsi[i]:
                    emit(i, "rsi_bounce", lo6)
                if rsi[i - 1] > 70 >= rsi[i]:
                    emit(i, "rsi_fade", hi6)
        if i == 2 and prev_close:
            if o[0] / prev_close - 1 >= 0.02 and c[i] > o[0]:
                emit(i, "gap_and_go", float(l[:3].min()))
    return out


def grade(sig: Dict[str, Any], later: pd.DataFrame) -> Dict[str, Any]:
    """Outcome on the bars after the signal: stop first if a bar touches both."""
    entry, stop, target, long = sig["entry"], sig["stop"], sig["target"], sig["side"] == "long"
    risk = abs(entry - stop)
    if len(later):
        hi, lo = later["high"].to_numpy(float), later["low"].to_numpy(float)
        hit_stop = lo <= stop if long else hi >= stop
        hit_tgt = hi >= target if long else lo <= target
        either = np.flatnonzero(hit_stop | hit_tgt)
        if len(either):
            k = int(either[0])
            if hit_stop[k]:
                return {"outcome": "stop", "exit": stop, "r": -1.0, "exit_ts": str(later.index[k])}
            return {"outcome": "target", "exit": target, "r": R_TARGET, "exit_ts": str(later.index[k])}
        last = float(later["close"].iloc[-1])
        r = ((last - entry) if long else (entry - last)) / risk
        return {"outcome": "close", "exit": round(last, 4), "r": round(r, 3), "exit_ts": str(later.index[-1])}
    return {"outcome": "open", "exit": None, "r": None, "exit_ts": None}


def scan(bars: pd.DataFrame, day=None, prev_close: Optional[float] = None) -> List[Dict[str, Any]]:
    """Signals on one day (default: the latest day in the bars)."""
    df = prepare(bars)
    days = sorted(df["day"].unique())
    if not days:
        return []
    day = day or days[-1]
    d = df[df["day"] == day]
    if prev_close is None:
        prior = [x for x in days if x < day]
        prev_close = float(df[df["day"] == prior[-1]]["close"].iloc[-1]) if prior else None
    return _signals_for_day(d, prev_close)


def backtest(bars_by_symbol: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    rows = []
    for sym, bars in bars_by_symbol.items():
        df = prepare(bars)
        days = sorted(df["day"].unique())
        for k, day in enumerate(days):
            if k < 5:
                continue                                   # rvol needs history
            d = df[df["day"] == day]
            prev_close = float(df[df["day"] == days[k - 1]]["close"].iloc[-1])
            for sig in _signals_for_day(d, prev_close):
                g = grade(sig, d.iloc[sig["i"] + 1:])
                if g["r"] is not None:
                    rows.append({"symbol": sym, "rule": sig["rule"], "r": g["r"], "outcome": g["outcome"]})
    by_rule = {}
    for rule in RULES:
        rs = [x["r"] for x in rows if x["rule"] == rule]
        if rs:
            a = np.array(rs)
            by_rule[rule] = {"n": len(rs), "win_rate": round(float((a > 0).mean()), 3), "avg_r": round(float(a.mean()), 3),
                             "target_rate": round(float(np.mean([x["outcome"] == "target" for x in rows if x["rule"] == rule])), 3),
                             "total_r": round(float(a.sum()), 2),
                             "t_stat": round(float(a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))), 2) if len(a) > 2 and a.std() > 0 else None}
    return {"symbols": len(bars_by_symbol), "trades": len(rows), "by_rule": by_rule,
            "note": "5-minute bars, last ~60 sessions; entry at the signal bar's close, stop first when a bar touches "
                    "both, exit at the close otherwise; no costs or slippage. avg_r > 0 with a t-stat above 2 is the "
                    "bar for 'this rule has an edge here'."}


# ── Paper journal ─────────────────────────────────────────────────────────

class Journal:
    def __init__(self, path: Optional[str] = None):
        self.path = str(path or JOURNAL)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._c() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY, symbol TEXT, rule TEXT, side TEXT,
                         ts TEXT, entry REAL, stop REAL, target REAL, rvol REAL, status TEXT DEFAULT 'open',
                         exit REAL, r REAL, exit_ts TEXT, created_at REAL, UNIQUE(symbol, rule, ts))""")

    def _c(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, sym: str, sig: Dict[str, Any]) -> Optional[int]:
        with self._c() as c:
            cur = c.execute("INSERT OR IGNORE INTO signals (symbol, rule, side, ts, entry, stop, target, rvol, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", (sym, sig["rule"], sig["side"], str(sig["ts"]), sig["entry"],
                                                          sig["stop"], sig["target"], sig.get("rvol"), time.time()))
            return cur.lastrowid if cur.rowcount else None

    def open(self) -> List[Dict[str, Any]]:
        return self._rows("WHERE status = 'open'")

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows(f"ORDER BY id DESC LIMIT {int(limit)}")

    def _rows(self, where: str) -> List[Dict[str, Any]]:
        with self._c() as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(f"SELECT * FROM signals {where}")]

    def settle(self, sid: int, g: Dict[str, Any]) -> None:
        with self._c() as c:
            c.execute("UPDATE signals SET status=?, exit=?, r=?, exit_ts=? WHERE id=?",
                      (g["outcome"], g["exit"], g["r"], g["exit_ts"], sid))

    def stats(self) -> Dict[str, Any]:
        with self._c() as c:
            rows = c.execute("SELECT rule, r FROM signals WHERE status != 'open' AND r IS NOT NULL").fetchall()
        out = {}
        for rule in RULES:
            rs = [r for ru, r in rows if ru == rule]
            if rs:
                out[rule] = {"n": len(rs), "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 3),
                             "avg_r": round(sum(rs) / len(rs), 3)}
        return out


def grade_open(journal: Journal, bars_for: callable) -> int:
    """Settle open paper signals against the bars since. A signal from a
    previous session that never hit stop or target is closed at that day's close."""
    n = 0
    for s in journal.open():
        try:
            bars = prepare(bars_for(s["symbol"]))
        except Exception:
            continue
        ts = pd.Timestamp(s["ts"])
        same_day = bars[(bars["day"] == ts.date()) & (bars.index > ts)]
        g = grade(s, same_day)
        session_over = bool(len(bars)) and bars["day"].iloc[-1] > ts.date()
        if g["outcome"] in ("stop", "target") or (g["outcome"] == "close" and session_over):
            journal.settle(s["id"], g)
            n += 1
    return n
