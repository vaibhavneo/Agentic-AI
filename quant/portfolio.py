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
    total = sum(vals.values()) + cash
    syms = sorted(set(vals) | set(target))
    px = {s: float(P.daily(s, 5, http)["close"].iloc[-1]) for s in syms}
    trades = []
    for s in syms:
        cur, want = vals.get(s, 0.0), target.get(s, 0.0) * total
        d = want - cur
        if abs(d) < min_trade_usd:
            continue
        trades.append({"symbol": s, "action": "add" if d > 0 else "reduce", "usd": round(d, 2),
                       "shares": round(d / px[s], 4), "price": round(px[s], 2),
                       "from_weight": round(cur / total, 4), "to_weight": round(target.get(s, 0.0), 4)})
    turnover = sum(abs(t["usd"]) for t in trades) / 2 / total if total else 0
    return {"total_value": round(total, 2), "trades": sorted(trades, key=lambda t: t["usd"]),
            "turnover": round(turnover, 4), "note": "Trades to move from current to target weights at the last close. "
                                                    "Taxes and costs are not included."}


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
           "drift": drift, "expected_return": expected_return if drift == "conservative" else round(hist_ret, 4),
           "assumptions": ("the portfolio's own daily returns over the history window, resampled in 21-day blocks; "
                           "weights held constant; " +
                           (f"the average re-centred on {expected_return:.0%} a year (the window returned "
                            f"{hist_ret:.1%} a year)" if drift == "conservative" else "the window's own average")
                           + ". A range of outcomes, not a forecast.")}
    if goal:
        out["goal"] = goal
        out["prob_goal"] = round(float((wealth[:, -1] >= goal).mean()), 3)
    return out
