"""Portfolio risk, optimization, rebalancing and long-term projection.

All from daily adjusted closes (quant/prices.py). Every result states its
window, as-of date and the assumptions behind it:

    risk(holdings)              volatility, beta vs SPY, max drawdown, 95% VaR / CVaR (1-day, historical),
                                correlations, each holding's share of total risk, diversification ratio
    optimize(symbols, method)   min_variance | max_sharpe | risk_parity — long-only, per-name cap,
                                shrunk estimates; in-sample, said so
    rebalance(holdings, target) the trades (shares and $) from current to target weights
    project(holdings, years)    block-bootstrap Monte Carlo of the portfolio: percentile bands per year,
                                chance of a loss, chance of reaching a goal, with monthly contributions

`holdings` is a list of {"symbol", "shares"} (or {"symbol", "value"}); prices
come from the last settled close. Nothing here is a recommendation to trade.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from quant import prices as P

TRADING_DAYS = 252
BENCH = "SPY"


def _values(holdings: Sequence[Dict[str, Any]], http=None) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for h in holdings:
        sym = str(h["symbol"]).upper()
        if h.get("value") is not None:
            out[sym] = out.get(sym, 0.0) + float(h["value"])
        else:
            px = float(P.daily(sym, 5, http)["close"].iloc[-1])
            out[sym] = out.get(sym, 0.0) + float(h["shares"]) * px
    return out


def _shrunk_cov(r: pd.DataFrame, delta: float = 0.2) -> np.ndarray:
    """Sample covariance shrunk toward its diagonal — fewer spurious hedges."""
    s = r.cov().values * TRADING_DAYS
    return (1 - delta) * s + delta * np.diag(np.diag(s))


def _max_drawdown(series: pd.Series) -> float:
    wealth = (1 + series).cumprod()
    return float((wealth / wealth.cummax() - 1).min())


def risk(holdings: Sequence[Dict[str, Any]], years: int = 3, http=None) -> Dict[str, Any]:
    vals = _values(holdings, http)
    syms = [s for s, v in vals.items() if v > 0]
    r = P.returns(syms + [BENCH], years, http)
    missing = [s for s in syms if s not in r.columns]
    syms = [s for s in syms if s in r.columns]
    if len(syms) < 1 or len(r) < 60:
        raise ValueError("not enough overlapping price history to measure risk")
    total = sum(vals[s] for s in syms)
    w = np.array([vals[s] / total for s in syms])
    R = r[syms]
    port = R.values @ w
    bench = r[BENCH].values if BENCH in r else None
    cov = R.cov().values * TRADING_DAYS
    port_vol = float(np.sqrt(w @ cov @ w))
    sig = np.sqrt(np.diag(cov))
    contrib = w * (cov @ w) / (port_vol ** 2) if port_vol > 0 else np.zeros_like(w)
    var95 = float(-np.percentile(port, 5))
    cvar95 = float(-port[port <= np.percentile(port, 5)].mean())
    beta = float(np.cov(port, bench)[0, 1] / np.var(bench, ddof=1)) if bench is not None else None
    corr = R.corr().round(2)
    per = []
    for i, s in enumerate(syms):
        b = float(np.cov(R[s].values, bench)[0, 1] / np.var(bench, ddof=1)) if bench is not None else None
        per.append({"symbol": s, "value": round(vals[s], 2), "weight": round(float(w[i]), 4),
                    "vol_ann": round(float(sig[i]), 4), "beta": round(b, 2) if b is not None else None,
                    "max_drawdown": round(_max_drawdown(R[s]), 4), "risk_share": round(float(contrib[i]), 4)})
    # The pair that most limits diversification.
    pairs = [(corr.iloc[i, j], syms[i], syms[j]) for i in range(len(syms)) for j in range(i + 1, len(syms))]
    top_pair = max(pairs) if pairs else None
    return {
        "as_of": str(r.index[-1].date()), "window": f"{r.index[0].date()} to {r.index[-1].date()} ({len(r)} days)",
        "total_value": round(total, 2), "holdings": sorted(per, key=lambda x: -x["weight"]),
        "portfolio": {"vol_ann": round(port_vol, 4), "beta": round(beta, 2) if beta is not None else None,
                      "max_drawdown": round(_max_drawdown(pd.Series(port)), 4),
                      "var95_1d": round(var95, 4), "cvar95_1d": round(cvar95, 4),
                      "var95_1d_usd": round(var95 * total, 2),
                      "return_ann": round(float((1 + port).prod() ** (TRADING_DAYS / len(port)) - 1), 4),
                      "diversification_ratio": round(float((w @ sig) / port_vol), 2) if port_vol else None,
                      "largest_risk": per and max(per, key=lambda x: x["risk_share"])["symbol"]},
        "most_correlated_pair": {"a": top_pair[1], "b": top_pair[2], "corr": float(top_pair[0])} if top_pair else None,
        "correlation": {"symbols": syms, "matrix": corr.values.tolist()},
        "missing": missing, "source": "Yahoo Finance daily adjusted closes",
    }


def optimize(symbols: Sequence[str], method: str = "max_sharpe", max_weight: float = 0.35, years: int = 3,
             rf: float = 0.04, http=None) -> Dict[str, Any]:
    from scipy.optimize import minimize
    syms = [s.upper() for s in dict.fromkeys(symbols)]
    r = P.returns(syms, years, http)
    syms = [s for s in syms if s in r.columns]
    n = len(syms)
    if n < 2:
        raise ValueError("an optimization needs at least two symbols with price history")
    cap = max(max_weight, 1.0 / n + 1e-9)
    cov = _shrunk_cov(r[syms])
    mu_hist = r[syms].mean().values * TRADING_DAYS
    mu = 0.5 * mu_hist + 0.5 * mu_hist.mean()       # shrink each name toward the average — less chasing of past winners
    w0 = np.full(n, 1.0 / n)
    bounds = [(0.0, cap)] * n
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    vol = lambda w: float(np.sqrt(w @ cov @ w))
    if method == "min_variance":
        obj = lambda w: w @ cov @ w
    elif method == "max_sharpe":
        obj = lambda w: -((w @ mu - rf) / vol(w))
    elif method == "risk_parity":
        def obj(w):
            rc = w * (cov @ w)
            return float(((rc / rc.sum() - 1.0 / n) ** 2).sum())
    else:
        raise ValueError("method must be min_variance, max_sharpe or risk_parity")
    res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=cons, options={"maxiter": 500, "ftol": 1e-12})
    w = np.clip(res.x, 0, None)
    w = w / w.sum()
    rc = w * (cov @ w) / (w @ cov @ w)
    return {
        "method": method, "as_of": str(r.index[-1].date()), "window": f"{years}y daily",
        "weights": {s: round(float(x), 4) for s, x in sorted(zip(syms, w), key=lambda t: -t[1]) if x >= 0.0005},
        "risk_share": {s: round(float(x), 4) for s, x in zip(syms, rc)},
        "expected_return_ann": round(float(w @ mu), 4), "vol_ann": round(vol(w), 4),
        "sharpe": round(float((w @ mu - rf) / vol(w)), 2), "rf": rf, "max_weight": round(cap, 4),
        "converged": bool(res.success),
        "assumptions": "in-sample: historical returns shrunk 50% toward their average, covariance shrunk 20% toward "
                       "its diagonal; long-only with a per-name cap. Past co-movement is not a promise.",
    }


def rebalance(holdings: Sequence[Dict[str, Any]], target: Dict[str, float], cash: float = 0.0,
              min_trade_usd: float = 50.0, http=None) -> Dict[str, Any]:
    vals = _values(holdings, http)
    cost = {}
    for h in holdings:
        if h.get("avg_cost") is not None and h.get("shares") is not None:
            cost[str(h["symbol"]).upper()] = float(h["avg_cost"])
    total = sum(vals.values()) + cash
    syms = sorted(set(vals) | set(target))
    px = {s: float(P.daily(s, 5, http)["close"].iloc[-1]) for s in syms}
    trades = []
    realized = 0.0
    for s in syms:
        cur, want = vals.get(s, 0.0), target.get(s, 0.0) * total
        d = want - cur
        if abs(d) < min_trade_usd:
            continue
        t = {"symbol": s, "action": "add" if d > 0 else "reduce", "usd": round(d, 2),
             "shares": round(d / px[s], 4), "price": round(px[s], 2),
             "from_weight": round(cur / total, 4), "to_weight": round(target.get(s, 0.0), 4)}
        if d < 0 and s in cost:
            # Average-cost estimate: the lots actually sold (and their holding periods) decide the real figure.
            t["est_realized_gain"] = round(-d / px[s] * (px[s] - cost[s]), 2)
            realized += t["est_realized_gain"]
        trades.append(t)
    turnover = sum(abs(t["usd"]) for t in trades) / 2 / total if total else 0
    # Rebalancing by adding money only: the new money that brings every name to its target without a sale.
    held = [s for s in vals if vals[s] > 0]
    if held and all(target.get(s, 0) > 0 for s in held):
        add_only = max(0.0, max(vals[s] / target[s] for s in held) - total)
    else:
        add_only = None                                  # a name with a 0% target can only be reached by selling
    out = {"total_value": round(total, 2), "trades": sorted(trades, key=lambda t: t["usd"]),
           "current_weights": {s: round(vals.get(s, 0.0) / total, 4) for s in syms} if total else {},
           "turnover": round(turnover, 4), "add_only_cash": round(add_only, 2) if add_only is not None else None,
           "note": "Trades to move from current to target weights at the last close. Costs are not included"
                   + ("; realized gains are average-cost estimates, before tax." if cost else "; add a cost basis "
                      "to see the gains a sale would realize.")}
    if cost:
        out["est_realized_gain"] = round(realized, 2)
    return out


def _portfolio_returns(holdings, history_years: int, drift: str, expected_return: float, http=None):
    vals = _values(holdings, http)
    syms = list(vals)
    r = P.returns(syms, history_years, http)
    syms = [s for s in syms if s in r.columns]
    if not syms or len(r) < 120:
        raise ValueError("not enough overlapping price history to simulate")
    total = sum(vals[s] for s in syms)
    w = np.array([vals[s] / total for s in syms])
    port = r[syms].values @ w
    hist_ret = float((1 + port).prod() ** (TRADING_DAYS / len(port)) - 1)
    if drift == "conservative":
        port = port - port.mean() + ((1 + expected_return) ** (1 / TRADING_DAYS) - 1)
    return port, total, hist_ret, r


def _simulate(port: np.ndarray, start: float, years: int, monthly: float, paths: int, block: int,
              seed: int) -> np.ndarray:
    """Year-end wealth per path (paths x years+1). Monthly flows (negative = withdrawals) are spread
    over the trading days; a path that hits zero stays at zero."""
    n_days = years * TRADING_DAYS
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(port) - block, size=(paths, int(np.ceil(n_days / block))))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(paths, -1)[:, :n_days]
    daily = port[idx]
    wealth = np.empty((paths, years + 1))
    wealth[:, 0] = start
    v = np.full(paths, float(start))
    flow = monthly * 12 / TRADING_DAYS
    for y in range(years):
        for d in range(y * TRADING_DAYS, (y + 1) * TRADING_DAYS):
            v = np.maximum(v * (1 + daily[:, d]) + flow, 0.0)
        wealth[:, y + 1] = v
    return wealth


def plan_goal(holdings: Sequence[Dict[str, Any]], goal: float, years: int = 10, probability: float = 0.7,
              paths: int = 2000, history_years: int = 5, drift: str = "conservative",
              expected_return: float = 0.07, seed: int = 7, http=None) -> Dict[str, Any]:
    """The monthly amount that reaches `goal` in `probability` of simulated paths.
    The same random paths for every candidate amount, so more money never
    looks worse (a bisection on a monotone curve)."""
    port, total, hist_ret, r = _portfolio_returns(holdings, history_years, drift, expected_return, http)

    def chance(m):
        return float((_simulate(port, total, years, m, paths, 21, seed)[:, -1] >= goal).mean())
    base = chance(0.0)
    if base >= probability:
        need = 0.0
    else:
        lo, hi = 0.0, max(100.0, goal / (years * 12))
        while chance(hi) < probability and hi < 1e7:
            hi *= 2
        for _ in range(16):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if chance(mid) >= probability else (mid, hi)
        need = hi
    return {"goal": goal, "years": years, "probability": probability, "start_value": round(total, 2),
            "monthly_needed": round(need, 0), "chance_without_adding": round(base, 3),
            "invested": round(total + need * 12 * years, 2), "paths": paths, "drift": drift,
            "expected_return": expected_return if drift == "conservative" else round(hist_ret, 4),
            "assumptions": f"{paths:,} block-bootstrap paths of this portfolio's daily returns"
                           + (f", the average year re-centred on {expected_return:.0%}" if drift == "conservative"
                              else ", the window's own average") + ". A range of outcomes, not a promise."}


def withdrawal(holdings: Sequence[Dict[str, Any]], annual_spend: float, years: int = 30, paths: int = 2000,
               history_years: int = 5, drift: str = "conservative", expected_return: float = 0.07,
               success: float = 0.9, seed: int = 7, http=None) -> Dict[str, Any]:
    """Spending `annual_spend` a year (monthly, flat in today's dollars — so the
    expected return should be a REAL one) from this portfolio: the chance the
    money lasts `years`, and the yearly amount that lasts in `success` of paths."""
    port, total, hist_ret, r = _portfolio_returns(holdings, history_years, drift, expected_return, http)

    def lasts(spend):
        w = _simulate(port, total, years, -spend / 12, paths, 21, seed)
        return w, float((w[:, -1] > 0).mean())
    w, p_ok = lasts(annual_spend)
    lo, hi = 0.0, total
    for _ in range(16):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if lasts(mid)[1] >= success else (lo, mid)
    depleted = (w <= 0).argmax(axis=1).astype(float)
    depleted[(w > 0).all(axis=1)] = np.nan
    return {"annual_spend": annual_spend, "years": years, "start_value": round(total, 2),
            "withdrawal_rate": round(annual_spend / total, 4) if total else None,
            "chance_it_lasts": round(p_ok, 3), "sustainable_spend": round(lo, 0), "success_target": success,
            "median_end": round(float(np.median(w[:, -1])), 0),
            "median_year_depleted": None if np.isnan(depleted).all() else float(np.nanmedian(depleted)),
            "percentiles": {q: [round(float(x), 0) for x in np.percentile(w, q, axis=0)] for q in (5, 50, 95)},
            "assumptions": f"{paths:,} block-bootstrap paths; spending flat each year (use a real, after-inflation "
                           f"expected return: {expected_return:.0%} here); taxes and fees not included. "
                           "A range of outcomes, not a plan."}


STRESS = [
    ("2008 financial crisis", "2007-10-09", "2009-03-09"),
    ("2018 Q4 selloff", "2018-09-20", "2018-12-24"),
    ("2020 COVID crash", "2020-02-19", "2020-03-23"),
    ("2022 bear market", "2022-01-03", "2022-10-12"),
    ("2023 rate shock", "2023-07-31", "2023-10-27"),
]


def stress(holdings: Sequence[Dict[str, Any]], http=None) -> Dict[str, Any]:
    """Each historical drawdown replayed on today's holdings: a holding's own
    return over the window when it traded then, otherwise its beta (last 3
    years) times the S&P 500's move — marked as an estimate."""
    vals = _values(holdings, http)
    total = sum(vals.values())
    hist = {s: P.daily(s, 20, http)["adjclose"] for s in list(vals) + [BENCH]}
    r3 = P.returns(list(vals) + [BENCH], 3, http)
    beta = {}
    for s in vals:
        if s in r3 and BENCH in r3:
            beta[s] = float(np.cov(r3[s], r3[BENCH])[0, 1] / np.var(r3[BENCH], ddof=1))
    out = []
    for name, a, b in STRESS:
        spy = hist[BENCH]
        sa, sb = spy[spy.index >= a], spy[spy.index <= b]
        if sa.empty or sb.empty:
            continue
        spy_ret = float(sb.iloc[-1] / sa.iloc[0] - 1)
        rows, port = [], 0.0
        for s, v in vals.items():
            px = hist[s]
            pa, pb = px[px.index >= a], px[px.index <= b]
            if len(px) and px.index[0] <= pd.Timestamp(a) and not pa.empty and not pb.empty:
                ret, how = float(pb.iloc[-1] / pa.iloc[0] - 1), "actual"
            else:
                ret, how = max(-0.95, beta.get(s, 1.0) * spy_ret), "beta estimate"
            port += v / total * ret
            rows.append({"symbol": s, "return": round(ret, 4), "basis": how})
        out.append({"scenario": name, "from": a, "to": b, "sp500": round(spy_ret, 4), "portfolio": round(port, 4),
                    "portfolio_usd": round(port * total, 2), "holdings": rows,
                    "estimated_share": round(sum(vals[r['symbol']] for r in rows if r["basis"] != "actual") / total, 3)})
    worst = min(out, key=lambda x: x["portfolio"]) if out else None
    return {"total_value": round(total, 2), "scenarios": out, "worst": worst and worst["scenario"],
            "note": "Today's holdings replayed through past drawdowns (start to end of each window, adjusted "
                    "closes). A holding that did not trade then is estimated from its 3-year beta to the S&P 500. "
                    "History, not a forecast; the next drawdown will not match any of these."}


def project(holdings: Sequence[Dict[str, Any]], years: int = 10, monthly_contribution: float = 0.0,
            goal: Optional[float] = None, paths: int = 4000, block: int = 21, history_years: int = 5,
            seed: int = 7, drift: str = "conservative", expected_return: float = 0.07, http=None) -> Dict[str, Any]:
    """Block bootstrap: resample 21-day blocks of the portfolio's own daily
    returns (constant weights, rebalanced), so volatility clustering and
    crashes survive. drift="conservative" (default) keeps that shape but
    re-centres the average on `expected_return` a year — a five-year window
    can hold an exceptional run, and replaying it as the expectation would
    overstate a decade. drift="historical" replays the window's own mean."""
    vals = _values(holdings, http)
    syms = list(vals)
    r = P.returns(syms, history_years, http)
    syms = [s for s in syms if s in r.columns]
    total = sum(vals[s] for s in syms)
    w = np.array([vals[s] / total for s in syms])
    port = r[syms].values @ w
    hist_ret = float((1 + port).prod() ** (TRADING_DAYS / len(port)) - 1)
    if drift == "conservative":
        port = port - port.mean() + ((1 + expected_return) ** (1 / TRADING_DAYS) - 1)
    n_days = years * TRADING_DAYS
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n_days / block))
    starts = rng.integers(0, len(port) - block, size=(paths, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(paths, -1)[:, :n_days]
    daily = port[idx]
    wealth = np.empty((paths, years + 1))
    wealth[:, 0] = total
    v = np.full(paths, total)
    contrib = monthly_contribution * 12 / TRADING_DAYS
    for y in range(years):
        seg = daily[:, y * TRADING_DAYS:(y + 1) * TRADING_DAYS]
        for d in range(seg.shape[1]):
            v = v * (1 + seg[:, d]) + contrib
        wealth[:, y + 1] = v
    invested = total + monthly_contribution * 12 * years
    pct = {p: [round(float(x), 0) for x in np.percentile(wealth, p, axis=0)] for p in (5, 25, 50, 75, 95)}
    out = {"years": years, "start_value": round(total, 2), "monthly_contribution": monthly_contribution,
           "invested": round(invested, 2), "paths": paths, "history": f"{r.index[0].date()} to {r.index[-1].date()}",
           "percentiles": pct, "median_end": pct[50][-1],
           "prob_loss": round(float((wealth[:, -1] < invested).mean()), 3),
           "hist_return_ann": round(hist_ret, 4),
           "hist_vol_ann": round(float(port.std() * np.sqrt(TRADING_DAYS)), 4),
           # The average year and the typical compounded year differ by the volatility drag.
           "typical_growth_ann": round(float(np.expm1(np.log1p(port).mean() * TRADING_DAYS)), 4),
           "drift": drift, "expected_return": expected_return if drift == "conservative" else round(hist_ret, 4),
           "assumptions": ("the portfolio's own daily returns over the history window, resampled in 21-day blocks; "
                           "weights held constant; " +
                           (f"the average year re-centred on {expected_return:.0%} (the window returned "
                            f"{hist_ret:.1%} a year)" if drift == "conservative" else "the window's own average")
                           + f"; at this volatility the typical compounded growth is "
                             f"{float(np.expm1(np.log1p(port).mean() * TRADING_DAYS)):.1%} a year"
                           + ". A range of outcomes, not a forecast.")}
    if goal:
        out["goal"] = goal
        out["prob_goal"] = round(float((wealth[:, -1] >= goal).mean()), 3)
    return out
