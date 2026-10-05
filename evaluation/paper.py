"""
Paper portfolio — what following the desk would have earned, net of costs.

A rank IC is a correlation; nobody can spend it. This turns the calls into the
two portfolios a person could actually have held and charges them for trading:

  LONG        equal weight in the top third of each rebalance date's names by
              score; compared with SPY and with the equal-weight universe (all
              names the desk covered that day). The universe is the honest
              benchmark for picking — it removes the "large caps vs the index"
              effect, which is not the desk's doing.
  LONG-SHORT  top third minus bottom third: the market-neutral version, which
              is what the rank IC actually measures.

Periods do NOT overlap: for a horizon h, rebalance dates are taken at least h
trading days apart and each period earns that date's h-day outcome. The t-stat
is therefore an ordinary one. Days with no call are days the portfolio is not
measured, not days it earned zero.

Costs: every unit of weight traded pays the cost model's per-trade cost for a
liquid name (backtest/costs.CostModel, no volume given — the conservative end).
A short leg pays the same to trade; borrow is ignored for these large caps and
stated as such.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from .stats import mean, r

TOP_FRACTION = 1.0 / 3.0
MIN_NAMES = 9


def default_cost_bps() -> float:
    try:
        from backtest.costs import CostModel
        return float(CostModel().per_trade_cost_bps(None))
    except Exception:
        return 5.0


def _rebalance_dates(dates: Sequence[str], horizon: int) -> List[str]:
    """Greedy: the first date, then each next date at least `horizon` trading
    days later, so holding periods never overlap."""
    out: List[str] = []
    for d in sorted(dates):
        if not out or np.busday_count(out[-1], d) >= horizon:
            out.append(d)
    return out


def _turnover(prev: Dict[str, float], new: Dict[str, float]) -> float:
    names = set(prev) | set(new)
    return sum(abs(new.get(n, 0.0) - prev.get(n, 0.0)) for n in names)


def _drawdown(curve: List[float]) -> float:
    peak, worst = 1.0, 0.0
    for v in curve:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst


def simulate(records: Sequence[Dict[str, Any]], horizon: int,
             score: Callable[[Dict[str, Any]], Optional[float]] = lambda x: x.get("composite"),
             cost_bps: Optional[float] = None) -> Dict[str, Any]:
    """records: scorecard.load(horizon) rows (raw and excess return at `horizon`)."""
    cost = default_cost_bps() if cost_bps is None else float(cost_bps)
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for x in records:
        if score(x) is not None and x.get("excess") is not None and x.get("call_date"):
            by_date.setdefault(x["call_date"], []).append(x)
    eligible = [d for d, xs in by_date.items() if len(xs) >= MIN_NAMES]
    dates = _rebalance_dates(eligible, horizon)

    periods = []
    prev_long: Dict[str, float] = {}
    prev_ls: Dict[str, float] = {}
    for d in dates:
        xs = sorted(by_date[d], key=lambda x: float(score(x)))
        k = max(1, int(len(xs) * TOP_FRACTION))
        top, bottom = xs[-k:], xs[:k]
        long_w = {x["ticker"]: 1.0 / k for x in top}
        ls_w = dict(long_w, **{x["ticker"]: -1.0 / k for x in bottom})
        spy = mean([x["raw"] - x["excess"] for x in xs])            # same SPY move for every name
        universe = mean([x["raw"] for x in xs])
        gross_long = mean([x["raw"] for x in top])
        gross_ls = gross_long - mean([x["raw"] for x in bottom])
        t_long, t_ls = _turnover(prev_long, long_w), _turnover(prev_ls, ls_w)
        net_long = gross_long - t_long * cost / 100.0                # returns are in %
        net_ls = gross_ls - t_ls * cost / 100.0
        periods.append({"date": d, "names": len(xs), "long_gross_pct": gross_long,
                        "long_net_pct": net_long, "long_short_net_pct": net_ls,
                        "universe_pct": universe, "spy_pct": spy,
                        "turnover_long": t_long, "turnover_long_short": t_ls})
        # Holdings drift with returns before the next rebalance; ignoring the
        # drift slightly understates turnover, which the conservative cost offsets.
        prev_long, prev_ls = long_w, ls_w

    if not periods:
        return {"horizon_days": horizon, "periods": 0, "cost_bps_per_trade": round(cost, 2),
                "reason": f"no rebalance date with {MIN_NAMES}+ scored names yet"}

    def curve(key):
        v, out = 1.0, []
        for p in periods:
            v *= 1.0 + p[key] / 100.0
            out.append(v)
        return out

    def stats(key):
        rets = [p[key] for p in periods]
        m = mean(rets)
        sd = float(np.std(rets, ddof=1)) if len(rets) > 1 else None
        per_year = 252.0 / horizon
        c = curve(key)
        return {"total_pct": r(100 * (c[-1] - 1), 2), "mean_period_pct": r(m, 3),
                "annualized_pct": r(100 * ((c[-1]) ** (per_year / len(rets)) - 1), 1) if c[-1] > 0 else None,
                "sharpe": r(m / sd * math.sqrt(per_year), 2) if sd else None,
                "max_drawdown_pct": r(100 * _drawdown(c), 2)}

    def vs(a, b):
        d = [p[a] - p[b] for p in periods]
        sd = float(np.std(d, ddof=1)) if len(d) > 1 else None
        return {"mean_period_pct": r(mean(d), 3),
                "t": r(mean(d) / (sd / math.sqrt(len(d))), 2) if sd else None,
                "share_of_periods_ahead": r(sum(1 for v in d if v > 0) / len(d), 3)}

    return {
        "horizon_days": horizon, "periods": len(periods),
        "first": periods[0]["date"], "last": periods[-1]["date"],
        "cost_bps_per_trade": round(cost, 2),
        "long": stats("long_net_pct"), "long_gross": stats("long_gross_pct"),
        "long_short": stats("long_short_net_pct"),
        "universe": stats("universe_pct"), "spy": stats("spy_pct"),
        "long_vs_universe": vs("long_net_pct", "universe_pct"),
        "long_vs_spy": vs("long_net_pct", "spy_pct"),
        "avg_turnover_long": r(mean([p["turnover_long"] for p in periods]), 3),
        "cost_drag_pct": r(sum(p["long_gross_pct"] - p["long_net_pct"] for p in periods), 3),
        "curve": [{"date": p["date"],
                   "long": r(c1, 4), "universe": r(c2, 4), "spy": r(c3, 4)}
                  for p, c1, c2, c3 in zip(periods, curve("long_net_pct"),
                                           curve("universe_pct"), curve("spy_pct"))],
    }
