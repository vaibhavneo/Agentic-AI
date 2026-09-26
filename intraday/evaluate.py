"""
Does anything predict intraday, once the spread is paid?

Structured around the fact that decides intraday questions: the gross signal and
the cost are the same order of magnitude. At a 20-day horizon the cross-sectional
study lost 64% of a +0.313% gross edge to 20bps. A 20-minute move in a liquid
large cap is on the order of 10-20bps, so a 2bps round trip is 10-20% of the
entire distribution the signal is trying to forecast — and at a 5-minute horizon
the cost can exceed the average absolute move altogether.

So this module never reports an IC on its own. Every horizon comes with the
BREAKEVEN: the mean absolute forward move, the cost, and what fraction of the
move the cost consumes. A feature with a respectable IC over a horizon whose
average move is smaller than the spread has found something real and unusable,
and those are different findings that must not be reported as the same one.

Independence is counted in non-overlapping windows, which is where intraday is
genuinely strong: 1,716 five-minute bars at a four-bar horizon contain ~429
non-overlapping windows, against 3 independent windows at the daily ledger's
252-day horizon. The caveat is regime rather than sample: vendor retention puts
the entire intraday sample inside one or two months, so this measures ONE market
period thoroughly rather than many periods at all.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .features import (FEATURES, MINUTES_IN, bars_to_minutes, compute,
                       forward_return, load)

# Round-trip cost in basis points: half-spread in, half-spread out, plus
# slippage. 2bps is a reasonable floor for a mega-cap at modest size and is
# already optimistic for anything smaller — the point is that it is stated and
# varied, not that this number is right for every name.
DEFAULT_COST_BPS = 2.0

# Horizons in bars. Kept short because that is where the independent-window
# count is high; anything approaching a session length reverts to the daily
# problem of few independent observations.
DEFAULT_HORIZONS = (1, 4, 12, 26)

# A feature needs this many usable observations before its IC is reported.
MIN_OBS = 200


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            / math.sqrt(sxx * syy))


def independent_windows(n_obs: int, horizon_bars: int) -> int:
    """Non-overlapping windows the sample can physically contain.

    The same ceiling intelligence.calibration.effective_sample_size applies to
    the daily ledger, expressed in bars. Overlapping windows share most of their
    path, so row count overstates evidence here exactly as it does there.
    """
    return max(0, int(n_obs // max(1, horizon_bars)))


def evaluate_symbol(symbol: str, interval: str = "5m", period: str = "1mo",
                    horizons: Sequence[int] = DEFAULT_HORIZONS,
                    cost_bps: float = DEFAULT_COST_BPS) -> Dict[str, Any]:
    """Every feature's IC at every horizon for one symbol, with the breakeven."""
    df = load(symbol, interval, period)
    if df is None or len(df) < 100:
        return {"symbol": symbol, "status": "NO_DATA",
                "reason": f"fewer than 100 {interval} bars available"}

    feats = compute(df, interval)
    out: Dict[str, Any] = {
        "symbol": symbol, "status": "OK", "interval": interval,
        "period": period, "n_bars": len(df),
        "n_sessions": int(feats["_session"].nunique()),
        "first_bar": str(df.index[0]), "last_bar": str(df.index[-1]),
        "cost_bps": cost_bps, "horizons": [],
    }

    for h in horizons:
        fwd = forward_return(df, h)
        usable = fwd.notna()
        n = int(usable.sum())
        if n < MIN_OBS:
            out["horizons"].append({
                "bars": h, "minutes": bars_to_minutes(h, interval),
                "status": "INSUFFICIENT", "n": n, "min_required": MIN_OBS})
            continue

        mean_abs_move_bps = float(fwd[usable].abs().mean()) * 100.0
        cost_share = (cost_bps / mean_abs_move_bps) if mean_abs_move_bps else None

        ics = {}
        for name in FEATURES:
            s = feats[name]
            m = usable & s.notna()
            if int(m.sum()) < MIN_OBS:
                ics[name] = None
                continue
            ics[name] = _pearson(s[m].tolist(), fwd[m].tolist())

        best = max((v for v in ics.values() if v is not None),
                   key=abs, default=None)
        out["horizons"].append({
            "bars": h,
            "minutes": bars_to_minutes(h, interval),
            "status": "OK",
            "n": n,
            "independent_windows": independent_windows(n, h),
            "mean_abs_move_bps": round(mean_abs_move_bps, 2),
            "cost_bps": cost_bps,
            "cost_as_share_of_move": (round(cost_share, 4)
                                      if cost_share is not None else None),
            "tradeable": bool(cost_share is not None and cost_share < 0.5),
            "ic": {k: (round(v, 5) if v is not None else None)
                   for k, v in ics.items()},
            "best_abs_ic": round(best, 5) if best is not None else None,
        })
    return out


def evaluate_universe(symbols: Sequence[str], interval: str = "5m",
                      period: str = "1mo",
                      horizons: Sequence[int] = DEFAULT_HORIZONS,
                      cost_bps: float = DEFAULT_COST_BPS) -> Dict[str, Any]:
    """Pooled across symbols, which is the only way to get a usable sample.

    Pooling is honest here in a way it would not be across dates: the names are
    distinct instruments observed over the SAME window, so the observations are
    cross-sectionally correlated but not serially stacked. Reported alongside the
    per-symbol spread so a single name cannot carry the pooled number.
    """
    per_symbol = []
    pooled: Dict[int, Dict[str, List[Any]]] = {h: {"f": {}, "y": []}
                                               for h in horizons}
    pooled_rows: Dict[int, List[Dict[str, Any]]] = {h: [] for h in horizons}

    for sym in symbols:
        df = load(sym, interval, period)
        if df is None or len(df) < 100:
            per_symbol.append({"symbol": sym, "status": "NO_DATA"})
            continue
        feats = compute(df, interval)
        res = {"symbol": sym, "status": "OK", "n_bars": len(df)}
        per_symbol.append(res)
        for h in horizons:
            fwd = forward_return(df, h)
            m = fwd.notna()
            for name in FEATURES:
                mm = m & feats[name].notna()
                if int(mm.sum()) == 0:
                    continue
                for x, y in zip(feats[name][mm].tolist(), fwd[mm].tolist()):
                    pooled_rows[h].append({"feature": name, "x": x, "y": y})

    out: Dict[str, Any] = {
        "interval": interval, "period": period, "cost_bps": cost_bps,
        "n_symbols": sum(1 for r in per_symbol if r.get("status") == "OK"),
        "per_symbol": per_symbol, "horizons": [],
    }

    for h in horizons:
        rows = pooled_rows[h]
        if not rows:
            out["horizons"].append({"bars": h, "status": "NO_DATA"})
            continue
        frame = pd.DataFrame(rows)
        ys = frame["y"]
        mean_abs = float(ys.abs().mean()) * 100.0
        cost_share = (cost_bps / mean_abs) if mean_abs else None
        ics = {}
        for name, grp in frame.groupby("feature"):
            if len(grp) < MIN_OBS:
                ics[name] = None
                continue
            ics[name] = _pearson(grp["x"].tolist(), grp["y"].tolist())
        best_name, best_ic = None, None
        for k, v in ics.items():
            if v is not None and (best_ic is None or abs(v) > abs(best_ic)):
                best_name, best_ic = k, v
        n_per_feature = int(len(frame) / max(1, len(ics)))
        out["horizons"].append({
            "bars": h, "minutes": bars_to_minutes(h, interval), "status": "OK",
            "n_observations": n_per_feature,
            "independent_windows_per_symbol": independent_windows(
                n_per_feature // max(1, out["n_symbols"]), h),
            "mean_abs_move_bps": round(mean_abs, 2),
            "cost_as_share_of_move": (round(cost_share, 4)
                                      if cost_share is not None else None),
            "tradeable": bool(cost_share is not None and cost_share < 0.5),
            "ic": {k: (round(v, 5) if v is not None else None)
                   for k, v in sorted(ics.items())},
            "best_feature": best_name,
            "best_abs_ic": round(best_ic, 5) if best_ic is not None else None,
            # What the signal must achieve to clear the spread. A correlation
            # this small on a move this small is the whole intraday problem.
            "ic_needed_to_cover_cost": (
                round(cost_bps / mean_abs, 4) if mean_abs else None),
        })
    return out
