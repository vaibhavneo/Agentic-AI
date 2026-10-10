"""Swing lab: daily-bar rules over five years of the desk's universe, measured honestly.

Rules (signal on a day's close, entry at the NEXT day's open; risk unit R = 2 x ATR(14)):

    breakout_20     close above the prior 20-day high, in an uptrend (close > 200-day average);
                    stop 1R, target 2R, out at the close of day 10
    breakdown_20    close below the prior 20-day low, in a downtrend (close < 200-day average) — short;
                    stop 1R, target 2R, out at the close of day 10
    rsi2_pullback   RSI(2) under 10 in an uptrend (Connors); out on the first close above the 5-day
                    average, or day 5; stop 1R
    bb_reversion    close under the lower Bollinger band (20, 2) in an uptrend; out on a close back at
                    the middle band, or day 10; stop 1R

HOW HONEST IT IS

    * baseline: the same rule's filter and exits from ordinary days (every 5th day) — in a bull market
      almost any long entry made money, so a rule only shows skill if it beats its own baseline.
    * stability: the average R in the first and second half of the window, separately.
    * t-stat on the rule's trades; one open trade per rule and symbol at a time.
    * survivorship: the universe is today's large caps, which flatters every long rule; said so.
    * no costs or slippage; a gap through the stop fills at the open, not the stop.

Nothing here places an order; signals are research.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from quant import prices as P

ROOT = Path(__file__).resolve().parents[1]
RULES = ("breakout_20", "breakdown_20", "rsi2_pullback", "bb_reversion")
LABEL = {"breakout_20": "20-day breakout (long)", "breakdown_20": "20-day breakdown (short)",
         "rsi2_pullback": "RSI(2) pullback in an uptrend (long)", "bb_reversion": "lower-band reversion (long)"}
SHORT = {"breakdown_20"}
MAX_DAYS = {"breakout_20": 10, "breakdown_20": 10, "rsi2_pullback": 5, "bb_reversion": 10}
NOTE = ("Daily bars, last ~5 years, today's large caps (survivorship flatters long rules). Entry at the next "
        "open, risk unit 2 x ATR(14), stop counted first when a day touches both, no costs. A rule shows skill "
        "only if it beats its own baseline (the same filter and exits on ordinary days) in both halves with a "
        "t-stat of 2+; even then, compare its edge per trade (in %) with costs of roughly 0.05-0.1% a round trip.")


def universe() -> List[str]:
    path = ROOT / "watchlist.txt"
    syms = [ln.split("#")[0].strip().upper() for ln in path.read_text().splitlines()] if path.exists() else []
    return [s for s in syms if s]


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame({k: df[k].astype(float) for k in ("open", "high", "low", "close")})
    # Adjust OHLC by the close's split/dividend factor so levels are comparable across the window.
    if "adjclose" in df:
        f = (df["adjclose"] / df["close"]).astype(float)
        for k in ("open", "high", "low", "close"):
            d[k] = d[k] * f
    c = d["close"]
    prev = c.shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - prev).abs(), (d["low"] - prev).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["sma5"], d["sma20"], d["sma200"] = c.rolling(5).mean(), c.rolling(20).mean(), c.rolling(200).mean()
    sd = c.rolling(20).std()
    d["bb_low"] = d["sma20"] - 2 * sd
    d["hi20"], d["lo20"] = d["high"].rolling(20).max().shift(1), d["low"].rolling(20).min().shift(1)
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    d["rsi2"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return d


def fires(d: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Boolean per rule per day (signal on that day's close)."""
    c, up = d["close"], d["close"] > d["sma200"]
    return {
        "breakout_20": ((c > d["hi20"]) & (c.shift(1) <= d["hi20"].shift(1)) & up).to_numpy(),
        "breakdown_20": ((c < d["lo20"]) & (c.shift(1) >= d["lo20"].shift(1)) & ~up & d["sma200"].notna()).to_numpy(),
        "rsi2_pullback": ((d["rsi2"] < 10) & up).to_numpy(),
        "bb_reversion": ((c < d["bb_low"]) & (c.shift(1) >= d["bb_low"].shift(1)) & up).to_numpy(),
    }


def filters(d: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Each rule's market filter alone — the baseline's entry days."""
    up = (d["close"] > d["sma200"]).to_numpy()
    down = ((d["close"] < d["sma200"]) & d["sma200"].notna()).to_numpy()
    return {"breakout_20": up, "breakdown_20": down, "rsi2_pullback": up, "bb_reversion": up}


def trade(d: pd.DataFrame, i: int, rule: str) -> Optional[Dict[str, Any]]:
    """Enter at day i+1's open; manage to stop / target / rule exit / time stop."""
    n = len(d)
    if i + 1 >= n or not np.isfinite(d["atr"].iat[i]) or d["atr"].iat[i] <= 0:
        return None
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    short = rule in SHORT
    entry, risk = float(o[i + 1]), 2.0 * float(d["atr"].iat[i])
    stop = entry + risk if short else entry - risk
    target = entry - 2 * risk if short else entry + 2 * risk
    last = min(n - 1, i + MAX_DAYS[rule])
    for j in range(i + 1, last + 1):
        # A gap through the stop fills at the open (worse than the stop).
        if (short and o[j] >= stop) or (not short and o[j] <= stop):
            if j > i + 1:
                ex = o[j]
                return _done(rule, i, j, entry, ex, risk, short, "stop_gap")
        if (short and h[j] >= stop) or (not short and l[j] <= stop):
            return _done(rule, i, j, entry, stop, risk, short, "stop")
        if rule in ("breakout_20", "breakdown_20") and ((short and l[j] <= target) or (not short and h[j] >= target)):
            return _done(rule, i, j, entry, target, risk, short, "target")
        if rule == "rsi2_pullback" and c[j] > d["sma5"].iat[j]:
            return _done(rule, i, j, entry, c[j], risk, short, "exit_rule")
        if rule == "bb_reversion" and c[j] >= d["sma20"].iat[j]:
            return _done(rule, i, j, entry, c[j], risk, short, "exit_rule")
    if last == n - 1 and last < i + MAX_DAYS[rule]:
        return None                                    # still open at the end of the data
    return _done(rule, i, last, entry, c[last], risk, short, "time")


def _done(rule, i, j, entry, ex, risk, short, why):
    r = ((entry - ex) if short else (ex - entry)) / risk
    return {"rule": rule, "i": i, "exit_i": j, "r": round(float(r), 3), "exit": why,
            "risk_pct": round(float(risk / entry), 4), "days": int(j - i)}


def run_symbol(df: pd.DataFrame, baseline_every: int = 5) -> Dict[str, List[Dict[str, Any]]]:
    d = indicators(df)
    out: Dict[str, List[Dict[str, Any]]] = {"trades": [], "baseline": []}
    f, base = fires(d), filters(d)
    dates = d.index
    for rule in RULES:
        busy_until = -1
        for i in np.flatnonzero(f[rule]):
            if i <= busy_until or i < 200:
                continue
            t = trade(d, int(i), rule)
            if t:
                t["date"] = str(dates[i].date())
                out["trades"].append(t)
                busy_until = t["exit_i"]
        for i in np.flatnonzero(base[rule])[::baseline_every]:
            if i < 200:
                continue
            t = trade(d, int(i), rule)
            if t:
                t["date"] = str(dates[i].date())
                out["baseline"].append(t)
    return out


def _stats(rs: Sequence[float]) -> Dict[str, Any]:
    a = np.asarray(rs, float)
    if not len(a):
        return {"n": 0}
    sd = a.std(ddof=1) if len(a) > 1 else 0.0
    return {"n": int(len(a)), "win_rate": round(float((a > 0).mean()), 3), "avg_r": round(float(a.mean()), 3),
            "t_stat": round(float(a.mean() / (sd / np.sqrt(len(a)))), 2) if sd > 0 else None}


def _daily(syms: Sequence[str], http=None) -> Dict[str, pd.DataFrame]:
    def one(s):
        try:
            return s, P.daily(s, 5, http)
        except Exception:
            return s, None
    with ThreadPoolExecutor(max_workers=6) as ex:
        return {s: df for s, df in ex.map(one, syms) if df is not None and len(df) > 260}


def backtest(symbols: Optional[Sequence[str]] = None, http=None, use_cache: bool = True) -> Dict[str, Any]:
    syms = [s.upper() for s in (symbols or universe())]
    key = hashlib.sha1(",".join(sorted(syms)).encode()).hexdigest()[:10]
    path = P.CACHE / f"swing_{key}_{datetime.now().date()}.json"
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    data = _daily(syms, http)
    trades, base = [], []
    for s, df in data.items():
        r = run_symbol(df)
        trades += [{**t, "symbol": s} for t in r["trades"]]
        base += [{**t, "symbol": s} for t in r["baseline"]]
    dates = sorted(t["date"] for t in trades + base)
    mid = dates[len(dates) // 2] if dates else ""
    by_rule = {}
    for rule in RULES:
        rt = [t for t in trades if t["rule"] == rule]
        bt = [t for t in base if t["rule"] == rule]
        s = _stats([t["r"] for t in rt])
        if not s["n"]:
            continue
        b = _stats([t["r"] for t in bt])
        h1 = _stats([t["r"] for t in rt if t["date"] < mid])
        h2 = _stats([t["r"] for t in rt if t["date"] >= mid])
        b1 = _stats([t["r"] for t in bt if t["date"] < mid])
        b2 = _stats([t["r"] for t in bt if t["date"] >= mid])
        edge = round(s["avg_r"] - b.get("avg_r", 0.0), 3)
        risk_pct = float(np.mean([t["risk_pct"] for t in rt]))
        s["avg_risk_pct"] = round(risk_pct, 4)
        s["avg_days"] = round(float(np.mean([t["days"] for t in rt])), 1)
        # In money: the edge per trade as a % of the position, next to a typical round-trip cost.
        s["edge_pct_per_trade"] = round(edge * risk_pct * 100, 3)
        both = all(x.get("n") and y.get("n") and x["avg_r"] > y["avg_r"] for x, y in ((h1, b1), (h2, b2)))
        by_rule[rule] = {**s, "label": LABEL[rule], "baseline": b, "edge_vs_baseline": edge,
                         "first_half": h1, "second_half": h2, "beats_baseline_both_halves": both,
                         "verdict": ("skill" if both and edge > 0 and (s.get("t_stat") or 0) >= 2 else
                                     "mixed" if edge > 0 else "no edge")}
    out = {"as_of": str(datetime.now().date()), "symbols": len(data), "trades": len(trades), "split_date": mid,
           "by_rule": by_rule, "note": NOTE}
    P.CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def scan(symbols: Optional[Sequence[str]] = None, http=None) -> Dict[str, Any]:
    """Rules that fired on the latest daily close: the plan for the next open, with each rule's record."""
    syms = [s.upper() for s in (symbols or universe())]
    bt = backtest(None if symbols is None else None, http=http)   # records always from the full universe
    rows, last = [], None
    for s, df in _daily(syms, http).items():
        d = indicators(df)
        f = fires(d)
        i = len(d) - 1
        last = max(last, d.index[i]) if last is not None else d.index[i]
        for rule in RULES:
            if f[rule][i]:
                close, risk = float(d["close"].iat[i]), 2.0 * float(d["atr"].iat[i])
                short = rule in SHORT
                rows.append({"symbol": s, "rule": rule, "label": LABEL[rule], "side": "short" if short else "long",
                             "date": str(d.index[i].date()), "close": round(close, 2),
                             "stop_ref": round(close + risk if short else close - risk, 2),
                             "target_ref": round(close - 2 * risk if short else close + 2 * risk, 2)
                             if rule in ("breakout_20", "breakdown_20") else None,
                             "exit_rule": {"rsi2_pullback": "first close above the 5-day average, or day 5",
                                           "bb_reversion": "a close back at the 20-day average, or day 10"}.get(
                                 rule, "2R target, or day 10"),
                             "record": bt["by_rule"].get(rule)})
    rows.sort(key=lambda r: (r["rule"], r["symbol"]))
    return {"as_of": str(last.date()) if last is not None else None, "signals": rows, "symbols": len(syms),
            "backtest": bt, "note": NOTE + " Levels are references from the signal close; the entry is the next open."}
