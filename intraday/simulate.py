"""
What the intraday signal actually pays after the spread.

The IC tells you a signal is related to the outcome. It does not tell you whether
trading it survives the cost, and at intraday horizons that is the only question
that matters — a 20-minute move averages under 20bps, so a 2bps round trip is a
tenth of the entire distribution being forecast.

So this simulates the trade rather than reasoning about the correlation. Each bar,
sort the cross-section on the signal, go long the top quintile and short the
bottom, hold `bars`, and charge the round trip on both legs. The output is a net
return per period and a t-statistic on it, which is the same bar the
cross-sectional daily study was held to (it produced t = 0.15).

Two properties deliberately preserved from the daily work:

  NON-OVERLAPPING windows only. Sampling every bar and holding 12 would count
  each move twelve times and inflate the t-statistic by roughly sqrt(12). Entries
  are therefore spaced `bars` apart.

  SAME-SESSION only. An overnight gap is not something an intraday signal
  forecasts, and leaving those windows in makes the gap the dominant term.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .evaluate import DEFAULT_COST_BPS
from .features import FEATURES, compute, forward_return, load

# Fraction of the cross-section taken on each side.
QUANTILE = 0.2

# A period needs this many names with a signal to form two sides worth trading.
MIN_NAMES = 6


def _t_stat(xs: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    if var <= 0:
        return None
    return mean / math.sqrt(var / n)


def simulate(symbols: Sequence[str], feature: str, bars: int,
             interval: str = "5m", period: str = "1mo",
             cost_bps: float = DEFAULT_COST_BPS,
             sign: float = -1.0) -> Dict[str, Any]:
    """Long/short the cross-section on one feature, held `bars` bars.

    `sign = -1` trades the feature CONTRARIAN, which is what the measured ICs
    call for: every price feature's IC is negative at every intraday horizon, so
    a high reading is a short. Stated as a parameter rather than hidden in the
    sort so the direction being traded is explicit and testable both ways.
    """
    panel_f: Dict[str, pd.Series] = {}
    panel_y: Dict[str, pd.Series] = {}

    for sym in symbols:
        df = load(sym, interval, period)
        if df is None or len(df) < 100:
            continue
        feats = compute(df, interval)
        if feature not in feats:
            continue
        panel_f[sym] = feats[feature]
        panel_y[sym] = forward_return(df, bars)

    if len(panel_f) < MIN_NAMES:
        return {"status": "INSUFFICIENT_NAMES", "n_names": len(panel_f),
                "min_required": MIN_NAMES}

    F = pd.DataFrame(panel_f).sort_index()
    Y = pd.DataFrame(panel_y).reindex(F.index)

    # Non-overlapping entries only.
    entries = F.index[::max(1, bars)]

    gross_list: List[float] = []
    net_list: List[float] = []
    n_used = 0
    for ts in entries:
        f_row = F.loc[ts].dropna()
        y_row = Y.loc[ts].dropna()
        common = f_row.index.intersection(y_row.index)
        if len(common) < MIN_NAMES:
            continue
        f_row, y_row = f_row[common], y_row[common]
        k = max(1, int(len(common) * QUANTILE))
        ordered = (f_row * sign).sort_values(ascending=False)
        longs = ordered.index[:k]
        shorts = ordered.index[-k:]
        gross = float(y_row[longs].mean() - y_row[shorts].mean())
        # Both legs pay the round trip.
        net = gross - 2.0 * (cost_bps / 100.0)
        gross_list.append(gross)
        net_list.append(net)
        n_used += 1

    if n_used < 10:
        return {"status": "INSUFFICIENT_PERIODS", "n_periods": n_used}

    mean_gross = sum(gross_list) / n_used
    mean_net = sum(net_list) / n_used
    t_net = _t_stat(net_list)
    wins = sum(1 for x in net_list if x > 0)

    from .features import BARS_PER_SESSION
    periods_per_session = max(1, BARS_PER_SESSION.get(interval, 78) // bars)
    periods_per_year = periods_per_session * 252
    stdev = (math.sqrt(sum((x - mean_net) ** 2 for x in net_list) / (n_used - 1))
             if n_used > 1 else 0.0)

    # PER-PERIOD Sharpe is the honest one and it is what gets reported.
    #
    # The annualized figure is computed but deliberately labelled as misleading
    # rather than headlined, because scaling a per-period Sharpe by
    # sqrt(1512) turns an ordinary 0.24 into 9.2 — a number no strategy has ever
    # sustained. The multiplication is arithmetically fine and the assumption
    # behind it is not: it presumes 1512 independent, uncorrelated, capacity-free
    # trades a year at constant edge. Intraday reversion decays with size,
    # crowds, and vanishes in the conditions that produce it. A reader shown 9.2
    # would conclude something the evidence cannot support, so the per-period
    # number leads.
    sharpe_period = (mean_net / stdev) if stdev > 0 else None
    sharpe_annualized_naive = ((mean_net / stdev) * math.sqrt(periods_per_year)
                               if stdev > 0 else None)

    return {
        "status": "OK",
        "feature": feature, "sign": sign, "bars": bars, "interval": interval,
        "n_names": len(panel_f), "n_periods": n_used,
        "quantile": QUANTILE, "cost_bps": cost_bps,
        "mean_gross_pct": round(mean_gross, 5),
        "mean_net_pct": round(mean_net, 5),
        "cost_drag_pct": round(2.0 * (cost_bps / 100.0), 5),
        "cost_share_of_gross": (round(2.0 * (cost_bps / 100.0) / mean_gross, 4)
                                if mean_gross > 0 else None),
        "win_rate": round(wins / n_used, 4),
        "t_stat_net": round(t_net, 3) if t_net is not None else None,
        "sharpe_per_period": (round(sharpe_period, 4)
                              if sharpe_period is not None else None),
        "sharpe_annualized_naive": (round(sharpe_annualized_naive, 2)
                                    if sharpe_annualized_naive is not None
                                    else None),
        "annualization_caveat": (
            f"the annualized figure assumes {periods_per_year} independent, "
            f"capacity-free trades a year at constant edge; treat the "
            f"per-period Sharpe as the real one"),
        "periods_per_year": periods_per_year,
        "verdict": _verdict(mean_net, t_net),
    }


def _verdict(mean_net: float, t_net: Optional[float]) -> str:
    if t_net is None:
        return "NOT_MEASURABLE"
    if mean_net <= 0:
        return "NEGATIVE_AFTER_COSTS"
    if t_net < 2.0:
        return "POSITIVE_BUT_NOT_SIGNIFICANT"
    return "POSITIVE_AND_SIGNIFICANT"


def sweep(symbols: Sequence[str], features: Sequence[str] = FEATURES,
          horizons: Sequence[int] = (4, 12, 26), interval: str = "5m",
          period: str = "1mo",
          cost_bps: float = DEFAULT_COST_BPS) -> Dict[str, Any]:
    """Every feature at every horizon, contrarian.

    A sweep is a multiple-comparisons problem and saying so is part of the
    result: testing 8 features at 3 horizons is 24 tries, so one t-statistic
    above 2 is roughly what chance alone produces. The Bonferroni-adjusted bar
    is reported next to the raw one for exactly that reason.
    """
    rows = []
    for f in features:
        for h in horizons:
            r = simulate(symbols, f, h, interval, period, cost_bps, sign=-1.0)
            if r.get("status") == "OK":
                rows.append(r)
    n_tests = max(1, len(rows))
    # Two-sided 5% Bonferroni, normal approximation.
    from statistics import NormalDist
    adj_t = NormalDist().inv_cdf(1 - 0.05 / (2 * n_tests))
    for r in rows:
        r["significant_raw"] = bool((r["t_stat_net"] or 0) >= 2.0)
        r["significant_adjusted"] = bool((r["t_stat_net"] or 0) >= adj_t)
    rows.sort(key=lambda r: -(r["t_stat_net"] or -99))
    return {"n_tests": n_tests, "bonferroni_t_threshold": round(adj_t, 3),
            "cost_bps": cost_bps, "results": rows}
