"""
Portfolio Plan — what you own, what's wrong with it, a risk-based rebalance,
and ideas from the screener. Built on top of Portfolio Decision Brief v2.

Why the rebalance is RISK-based: it makes no return forecast. The app's own
evaluations found its return signals not statistically significant
(docs/FUNDAMENTALS_V2_EVALUATION.md, the dSR-gated strategies), so a plan that
moves money toward "what will go up" would be dressing an unproven signal as a
trade list. Risk is measurable from prices alone, so the targets only answer
"how much risk is each position adding?". The engine's own ADD/TRIM/EXIT calls
stay visible beside the plan, and any disagreement is flagged, not hidden.

Method — stated priors, none fitted against outcomes:
  1. Equal risk contribution (ERC) over holdings with at least MIN_OBS days of
     returns: each ends up adding the same share of portfolio volatility, so a
     volatile name, or a cluster of names that move together, gets less money.
     Covariance is the 1-year daily one, shrunk SHRINK toward its diagonal so a
     short or collinear history can't produce a degenerate solution.
  2. Caps: no position above max_weight_pct and no known sector above
     max_sector_pct (the brief's own ceilings). Excess is spread over the
     uncapped names in proportion. A cap that can't be met with the names held
     (three stocks can't each be <= 25%) is raised to the lowest feasible value
     and said so.
  3. Trades only where a weight is off by more than DRIFT_BAND_PCT points and
     at least MIN_TRADE_USD, so the plan doesn't churn small positions.
  Holdings without enough history (or no current price) keep today's weight.
  Cash is kept at today's share unless a target is given. Crypto is shown but
  not rebalanced: Robinhood's API reports it only as a total.

Like portfolio_brief, a PURE CONSUMER: no fetching, no providers, no LLM. The
caller passes price returns and screener rows in. Nothing here places a trade.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from agents.portfolio_brief import (CORR_THRESHOLD, DEFAULT_MAX_SECTOR_PCT,
                                    DEFAULT_MAX_WEIGHT_PCT)

TRADING_DAYS = 252
MIN_OBS = 120                # ~6 months of daily returns for a covariance
SHRINK = 0.10                # toward the diagonal
DRIFT_BAND_PCT = 2.0         # points of the account
MIN_TRADE_USD = 25.0
IDLE_CASH_PCT = 10.0
RISK_SHARE_FLAG_PCT = 20.0   # a holding carrying at least this much of the risk...
RISK_SHARE_RATIO = 1.5       # ...and this many times its share of the money
LOW_EFFECTIVE_N = 5.0
IDEA_MIN_SCORE = 60.0
IDEA_DIVERSIFIER_CORR = 0.5
MAX_IDEAS = 6

DISCLAIMER = ("Rule-based suggestions from computed data, not financial advice. This app cannot "
              "place trades; anything you act on, you place yourself in Robinhood.")


# ── Risk math ─────────────────────────────────────────────────────────────

def _covariance(tickers: List[str], returns: Dict[str, pd.Series]
                ) -> Tuple[List[str], Optional[np.ndarray]]:
    """Annualized, shrunk covariance over the tickers with >= MIN_OBS
    overlapping daily returns. Returns (tickers_used, cov)."""
    series = {t: returns[t] for t in tickers
              if t in returns and returns[t] is not None and len(returns[t].dropna()) >= MIN_OBS}
    if not series:
        return [], None
    frame = pd.DataFrame(series).dropna()
    if len(frame) < MIN_OBS:
        # Overlap too short as a set: keep the longest-history names that do overlap.
        keep = sorted(series, key=lambda t: -len(series[t].dropna()))
        while keep and len(pd.DataFrame({t: series[t] for t in keep}).dropna()) < MIN_OBS:
            keep.pop()
        if not keep:
            return [], None
        frame = pd.DataFrame({t: series[t] for t in keep}).dropna()
    cols = list(frame.columns)
    cov = np.cov(frame.values, rowvar=False) * TRADING_DAYS
    cov = np.atleast_2d(cov)
    cov = (1 - SHRINK) * cov + SHRINK * np.diag(np.diag(cov))
    return cols, cov


def erc_weights(cov: np.ndarray, tol: float = 1e-10, max_iter: int = 10_000) -> np.ndarray:
    """Equal-risk-contribution weights (sum to 1) by cyclical coordinate
    descent on  ½·y'Σy − Σ ln(y_i)/n  (Griveau-Billion, Richard & Roncalli,
    2013), which converges for any positive-definite Σ."""
    n = cov.shape[0]
    if n == 1:
        return np.array([1.0])
    b = np.full(n, 1.0 / n)
    y = 1.0 / np.sqrt(np.diag(cov))
    y = y / y.sum()
    for _ in range(max_iter):
        y_prev = y.copy()
        for i in range(n):
            s = cov[i] @ y - cov[i, i] * y[i]
            y[i] = (-s + np.sqrt(s * s + 4 * cov[i, i] * b[i])) / (2 * cov[i, i])
        if np.max(np.abs(y - y_prev)) < tol:
            break
    return y / y.sum()


def risk_shares(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Each position's share of portfolio variance (sums to 1)."""
    var = float(w @ cov @ w)
    if var <= 0:
        return np.zeros_like(w)
    return w * (cov @ w) / var


def _apply_caps(w: Dict[str, float], sectors: Dict[str, str], pos_cap: float,
                sector_cap: float, fixed: Dict[str, float]) -> Tuple[Dict[str, float], float]:
    """Clip positions to pos_cap and known sectors to sector_cap (fractions of
    the account), spreading the excess over the names still below both caps in
    proportion to their weight. `fixed` names count toward sector totals but
    are never moved. Returns (weights, excess that had nowhere to go)."""
    w = dict(w)
    leftover = 0.0
    eps = 1e-9
    for _ in range(200):
        excess = 0.0
        capped = set()
        for t, v in w.items():
            if v > pos_cap + eps:
                excess += v - pos_cap
                w[t] = pos_cap
            if w[t] >= pos_cap - eps:
                capped.add(t)
        full_sectors = set()
        by_sector: Dict[str, float] = {}
        for t, v in list(w.items()) + list(fixed.items()):
            s = sectors.get(t, "Unknown")
            if s != "Unknown":
                by_sector[s] = by_sector.get(s, 0.0) + v
        for s, tot in by_sector.items():
            movable = [t for t in w if sectors.get(t) == s]
            room = sector_cap - sum(v for t, v in fixed.items() if sectors.get(t) == s)
            mov_tot = sum(w[t] for t in movable)
            if tot > sector_cap + eps and mov_tot > 0:
                scale = max(room, 0.0) / mov_tot
                for t in movable:
                    excess += w[t] * (1 - scale)
                    w[t] *= scale
            if by_sector[s] >= sector_cap - eps or tot > sector_cap + eps:
                full_sectors.add(s)
        if excess <= eps:
            break
        free = [t for t in w if t not in capped and sectors.get(t, "Unknown") not in full_sectors]
        free_tot = sum(w[t] for t in free)
        if not free or free_tot <= 0:
            leftover += excess
            break
        for t in free:
            w[t] += excess * w[t] / free_tot
    return w, leftover


# ── The plan ──────────────────────────────────────────────────────────────

def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _r(v, d=2):
    return None if v is None else round(float(v), d)


def build_plan(brief: Dict[str, Any],
               returns: Optional[Dict[str, pd.Series]] = None,
               cash_usd: Optional[float] = None,
               crypto_usd: Optional[float] = None,
               max_weight_pct: float = DEFAULT_MAX_WEIGHT_PCT,
               max_sector_pct: float = DEFAULT_MAX_SECTOR_PCT,
               cash_target_pct: Optional[float] = None,
               screener: Optional[Dict[str, Any]] = None,
               candidate_returns: Optional[Dict[str, pd.Series]] = None) -> Dict[str, Any]:
    """brief: the dict build_portfolio_brief returned (holdings + portfolio).
    returns: {ticker: daily-return Series}, the same 1-year series the brief's
      correlation step used. screener: stock_analysis.screener.latest() or None.
    Returns {"available", "overview", "diagnosis", "rebalance", "ideas",
    "method", "disclaimer"}."""
    returns = returns or {}
    holdings = [h for h in (brief.get("holdings") or []) if h.get("ticker")]
    if not holdings:
        return {"available": False, "reason": "No holdings."}

    cash = max(_num(cash_usd) or 0.0, 0.0)
    crypto = max(_num(crypto_usd) or 0.0, 0.0)

    pos = []
    for h in holdings:
        price = _num(h.get("current_price"))
        shares = _num(h.get("shares")) or 0.0
        avg_cost = _num(h.get("avg_cost"))
        mv = _num(h.get("market_value"))
        if mv is None and avg_cost is not None:
            mv = avg_cost * shares          # unpriced: carried at cost, never traded
        pos.append({
            "ticker": str(h["ticker"]).upper(), "sector": h.get("sector") or "Unknown",
            "shares": shares, "avg_cost": avg_cost, "price": price, "value": mv or 0.0,
            "cost": (avg_cost * shares) if avg_cost is not None else None,
            "engine_action": h.get("position_action"),
            "engine_reason": (h.get("reasons") or [None])[0],
        })

    invested = sum(p["value"] for p in pos)
    base = invested + cash                  # what the plan rebalances
    if base <= 0:
        return {"available": False, "reason": "Holdings have no value to rebalance."}
    for p in pos:
        p["weight"] = p["value"] / base

    tickers = [p["ticker"] for p in pos]
    sectors = {p["ticker"]: p["sector"] for p in pos}
    by_t = {p["ticker"]: p for p in pos}

    # ── Eligibility + covariance ──
    priced = [t for t in tickers if by_t[t]["price"]]
    cov_names, cov = _covariance(priced, returns)
    eligible = list(cov_names)
    frozen = {t: by_t[t]["weight"] for t in tickers if t not in eligible}
    frozen_reason = {t: ("no current price" if not by_t[t]["price"]
                         else f"less than {MIN_OBS} trading days of price history")
                     for t in frozen}

    cash_now = cash / base
    cash_goal = cash_now if cash_target_pct is None else min(max(cash_target_pct / 100.0, 0.0), 0.95)
    available = max(1.0 - cash_goal - sum(frozen.values()), 0.0)

    flags: List[str] = []
    pos_cap = max_weight_pct / 100.0
    sector_cap = max_sector_pct / 100.0
    if eligible and available > 0:
        if len(eligible) * pos_cap < available - 1e-9:
            pos_cap = available / len(eligible)
            flags.append(f"With {len(eligible)} holdings the {max_weight_pct:.0f}% position cap can't be met "
                         f"while staying invested; the plan uses {pos_cap * 100:.1f}% instead.")
        known_sectors = {sectors[t] for t in eligible if sectors[t] != "Unknown"}
        unknown_share = sum(1 for t in eligible if sectors[t] == "Unknown") * pos_cap
        if known_sectors and len(known_sectors) * sector_cap + unknown_share < available - 1e-9:
            sector_cap = max((available - unknown_share) / len(known_sectors), sector_cap)
            flags.append(f"Your stocks span {len(known_sectors)} sector(s), so the {max_sector_pct:.0f}% sector cap "
                         f"can't be met without adding other sectors (see Ideas); the plan uses "
                         f"{sector_cap * 100:.1f}% instead.")

    target: Dict[str, float] = dict(frozen)
    to_cash = 0.0
    erc: Dict[str, float] = {}
    if eligible:
        ew = erc_weights(cov)
        erc = {t: float(v) for t, v in zip(eligible, ew)}
        capped, to_cash = _apply_caps({t: erc[t] * available for t in eligible}, sectors,
                                      pos_cap, sector_cap, fixed=frozen)
        target.update(capped)
        if to_cash > 1e-6:
            full = sorted({sectors[t] for t in eligible if sectors[t] != "Unknown" and sum(
                target.get(u, 0.0) for u in tickers if sectors[u] == sectors[t]) >= sector_cap - 1e-6})
            at_cap = sorted(t for t in eligible if target.get(t, 0.0) >= pos_cap - 1e-6)
            bound = [f"{s} at the {sector_cap * 100:.0f}% sector cap" for s in full]
            if at_cap:
                bound.append(f"{', '.join(at_cap)} at the {pos_cap * 100:.0f}% stock cap")
            flags.append(f"{to_cash * 100:.1f}% stays in cash because every holding is at a cap "
                         f"({'; '.join(bound)}). Adding stocks in other sectors (see Ideas) would let it "
                         "be invested.")
    cash_target = 1.0 - sum(target.values())

    # ── Risk view (eligible names only; cash carries no risk) ──
    def risk_view(weights: Dict[str, float]) -> Dict[str, Any]:
        if cov is None:
            return {"vol_pct": None, "shares": {}}
        w = np.array([weights.get(t, 0.0) for t in eligible])
        rs = risk_shares(w, cov)
        return {"vol_pct": _r(np.sqrt(max(float(w @ cov @ w), 0.0)) * 100, 1),
                "shares": {t: float(s) for t, s in zip(eligible, rs)}}

    now_w = {t: by_t[t]["weight"] for t in tickers}
    risk_now, risk_after = risk_view(now_w), risk_view(target)

    def metrics(weights: Dict[str, float], risk: Dict[str, Any], cash_w: float) -> Dict[str, Any]:
        inv = {t: v for t, v in weights.items() if v > 0}
        tot = sum(inv.values())
        sec: Dict[str, float] = {}
        for t, v in inv.items():
            if sectors[t] != "Unknown":
                sec[sectors[t]] = sec.get(sectors[t], 0.0) + v
        top_sector = max(sec.items(), key=lambda kv: kv[1]) if sec else None
        top_pos = max(inv.items(), key=lambda kv: kv[1]) if inv else None
        top_risk = max(risk["shares"].items(), key=lambda kv: kv[1]) if risk["shares"] else None
        return {
            "volatility_pct": risk["vol_pct"],
            "largest_position": {"ticker": top_pos[0], "pct": _r(top_pos[1] * 100, 1)} if top_pos else None,
            "largest_sector": {"sector": top_sector[0], "pct": _r(top_sector[1] * 100, 1)} if top_sector else None,
            "effective_holdings": _r(1.0 / sum((v / tot) ** 2 for v in inv.values()), 1) if tot > 0 else None,
            "top_risk_share": {"ticker": top_risk[0], "pct": _r(top_risk[1] * 100, 1)} if top_risk else None,
            "cash_pct": _r(cash_w * 100, 1),
        }

    before = metrics(now_w, risk_now, cash_now)
    after = metrics(target, risk_after, cash_target)

    # ── Trades ──
    trades = []
    buys = sells = 0.0
    for t in tickers:
        p = by_t[t]
        tw = target.get(t, p["weight"])
        dw = tw - p["weight"]
        usd = dw * base
        row = {"ticker": t, "sector": p["sector"], "now_pct": _r(p["weight"] * 100),
               "target_pct": _r(tw * 100), "change_pct": _r(dw * 100),
               "engine_action": p["engine_action"], "side": "KEEP", "usd": 0.0, "shares": 0.0,
               "note": None}
        if t in frozen:
            row["note"] = f"Kept as is: {frozen_reason[t]}."
        elif abs(dw) * 100 >= DRIFT_BAND_PCT and abs(usd) >= MIN_TRADE_USD and p["price"]:
            row["side"] = "BUY" if usd > 0 else "SELL"
            row["usd"] = _r(abs(usd))
            row["shares"] = round(abs(usd) / p["price"], 4)
            if usd > 0:
                buys += abs(usd)
            else:
                sells += abs(usd)
            if row["side"] == "BUY" and p["engine_action"] in ("EXIT", "TRIM"):
                row["note"] = (f"The engine says {p['engine_action']} — the risk plan would add. "
                               "Review before buying.")
            elif row["side"] == "SELL" and p["engine_action"] == "ADD":
                row["note"] = "The engine says ADD — the risk plan would trim for diversification."
        trades.append(row)
    trades.sort(key=lambda r: (r["side"] == "KEEP", -(r["usd"] or 0)))

    # ── Overview ──
    by_sector_now: Dict[str, float] = {}
    for p in pos:
        by_sector_now[p["sector"]] = by_sector_now.get(p["sector"], 0.0) + p["weight"]
    cost_total = sum(p["cost"] for p in pos if p["cost"] is not None)
    overview = {
        "total_usd": _r(base + crypto), "invested_usd": _r(invested), "cash_usd": _r(cash),
        "crypto_usd": _r(crypto) if crypto else None,
        "cash_pct": _r(cash_now * 100, 1),
        "cost_basis_usd": _r(cost_total) if cost_total else None,
        "unrealized_pl_usd": _r(invested - cost_total) if cost_total else None,
        "unrealized_pl_pct": _r((invested - cost_total) / cost_total * 100, 1) if cost_total else None,
        "n_holdings": len(pos),
        "positions": [{"ticker": p["ticker"], "sector": p["sector"], "value_usd": _r(p["value"]),
                       "pct": _r(p["weight"] * 100, 1),
                       "risk_share_pct": _r(risk_now["shares"].get(p["ticker"], 0) * 100, 1)
                       if p["ticker"] in risk_now["shares"] else None}
                      for p in sorted(pos, key=lambda p: -p["value"])],
        "by_sector": [{"sector": s, "pct": _r(v * 100, 1)}
                      for s, v in sorted(by_sector_now.items(), key=lambda kv: -kv[1])],
    }

    diagnosis = _diagnose(pos, base, cash_now, crypto, max_weight_pct, max_sector_pct,
                          risk_now, eligible, returns, frozen_reason, before, flags,
                          (brief.get("portfolio") or {}).get("fundamental_red_flags") or [])

    rebalance = {
        "available": bool(eligible),
        "reason": None if eligible else "No holding has enough price history to estimate risk.",
        "caps": {"position_pct": _r(pos_cap * 100, 1), "sector_pct": _r(sector_cap * 100, 1),
                 "requested_position_pct": max_weight_pct, "requested_sector_pct": max_sector_pct},
        "cash_target_pct": _r(cash_target * 100, 1),
        "before": before, "after": after, "trades": trades,
        "totals": {"buy_usd": _r(buys), "sell_usd": _r(sells), "net_cash_usd": _r(sells - buys),
                   "cash_after_usd": _r(cash + sells - buys)},
        "notes": flags,
    }

    return {
        "available": True,
        "overview": overview,
        "diagnosis": diagnosis,
        "rebalance": rebalance,
        "ideas": _ideas(screener, set(tickers), pos, eligible, now_w, returns, candidate_returns),
        "method": (f"Equal risk contribution over 1-year daily returns (shrunk {int(SHRINK * 100)}% toward the "
                   f"diagonal), capped at {max_weight_pct:.0f}% per stock and {max_sector_pct:.0f}% per sector; "
                   f"trades only where a weight is off by more than {DRIFT_BAND_PCT:.0f} points and "
                   f"${MIN_TRADE_USD:.0f}. No return forecast is used."),
        "disclaimer": DISCLAIMER,
    }


# ── Diagnosis ─────────────────────────────────────────────────────────────

def _diagnose(pos, base, cash_now, crypto, max_weight_pct, max_sector_pct, risk_now,
              eligible, returns, frozen_reason, before, flags, red_flags) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def add(severity, kind, title, detail=None, tickers=None):
        out.append({"severity": severity, "kind": kind, "title": title, "detail": detail,
                    "tickers": tickers or []})

    for p in sorted(pos, key=lambda p: -p["weight"]):
        if p["weight"] * 100 > max_weight_pct:
            add("high", "position_over_cap",
                f"{p['ticker']} is {p['weight'] * 100:.1f}% of your account (cap {max_weight_pct:.0f}%).",
                "One stock this large decides most of your result.", [p["ticker"]])

    sec: Dict[str, List[str]] = {}
    sec_w: Dict[str, float] = {}
    for p in pos:
        if p["sector"] != "Unknown":
            sec.setdefault(p["sector"], []).append(p["ticker"])
            sec_w[p["sector"]] = sec_w.get(p["sector"], 0.0) + p["weight"]
    for s, w in sorted(sec_w.items(), key=lambda kv: -kv[1]):
        if w * 100 > max_sector_pct:
            add("high", "sector_over_cap",
                f"{s} is {w * 100:.1f}% of your account (cap {max_sector_pct:.0f}%).",
                f"Holdings: {', '.join(sec[s])}. A sector this large is one macro bet.", sec[s])

    def _why(ps):
        # One holding: its reason. Several: the reasons are per holding and long,
        # and they live one click away in the holdings table.
        if len(ps) == 1:
            return ps[0]["engine_reason"]
        return "Open each holding (▸) in the table below for the engine's reasons."

    exits = [p for p in pos if p["engine_action"] == "EXIT"]
    if exits:
        add("high", "engine_exit",
            f"The engine flags {', '.join(p['ticker'] for p in exits)} to EXIT.",
            _why(exits), [p["ticker"] for p in exits])

    inv_w = {p["ticker"]: p["weight"] for p in pos if p["ticker"] in eligible}
    inv_tot = sum(inv_w.values())
    for t, rs in sorted(risk_now["shares"].items(), key=lambda kv: -kv[1]):
        money = inv_w.get(t, 0) / inv_tot if inv_tot else 0
        if rs * 100 >= RISK_SHARE_FLAG_PCT and money > 0 and rs >= RISK_SHARE_RATIO * money:
            add("medium", "risk_concentration",
                f"{t} is {money * 100:.0f}% of your stock money but {rs * 100:.0f}% of its risk.",
                "It swings more than the rest, or moves with them, so it drives most of the ups and downs.", [t])

    pairs = []
    names = [t for t in eligible if t in returns]
    if len(names) >= 2:
        frame = pd.DataFrame({t: returns[t] for t in names}).dropna()
        if len(frame) >= MIN_OBS:
            corr = frame.corr()
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    c = float(corr.loc[a, b])
                    if c >= CORR_THRESHOLD:
                        pairs.append((c, a, b))
    for c, a, b in sorted(pairs, reverse=True)[:3]:
        add("medium", "correlated_pair",
            f"{a} and {b} move together (correlation {c:.2f}).",
            "Owning both is partly the same bet twice.", [a, b])

    trims = [p for p in pos if p["engine_action"] == "TRIM"]
    if trims:
        add("medium", "engine_trim",
            f"The engine suggests trimming {', '.join(p['ticker'] for p in trims)}.",
            _why(trims), [p["ticker"] for p in trims])

    for rf in red_flags:
        concerns = rf.get("concerns") or []
        if concerns:
            add("medium", "filing_red_flag",
                f"{rf.get('ticker')}: its SEC filings raise concerns.",
                "; ".join(concerns[:3]), [rf.get("ticker")])

    if cash_now * 100 >= IDLE_CASH_PCT:
        add("info", "idle_cash", f"{cash_now * 100:.0f}% of your account is cash (${cash_now * base:,.0f}).",
            "Not a problem if it's deliberate; it earns little and doesn't grow with the market.")

    eff = before.get("effective_holdings")
    if eff is not None and len(pos) >= 2 and eff < LOW_EFFECTIVE_N:
        add("info", "low_diversification",
            f"Your stocks behave like about {eff:.1f} equal-sized positions.",
            f"{len(pos)} holdings, but the money is concentrated in a few of them.")

    for t, why in frozen_reason.items():
        add("info", "not_rebalanced", f"{t} is left out of the rebalance: {why}.", None, [t])
    if crypto:
        add("info", "crypto_total",
            f"${crypto:,.0f} in crypto is shown but not rebalanced.",
            "Robinhood's API reports crypto only as a total, not per coin.")
    for f in flags:
        add("info", "cap_infeasible", f)

    if not any(d["severity"] in ("high", "medium") for d in out):
        out.insert(0, {"severity": "ok", "kind": "no_issues",
                       "title": "No concentration, overlap or engine warnings against these rules.",
                       "detail": None, "tickers": []})
    return out


# ── Ideas from the screener ───────────────────────────────────────────────

def idea_candidates(screener: Optional[Dict[str, Any]], held: set, limit: int = 8) -> List[Dict[str, Any]]:
    """Screener names you don't own: no filing concerns, fundamentals score >=
    IDEA_MIN_SCORE, best score first. The endpoint fetches prices for exactly
    these, so their correlation with your portfolio can be measured."""
    from stock_analysis.screener import screen
    rows = (screener or {}).get("rows") or []
    picks = screen(rows, min_score=IDEA_MIN_SCORE, no_filing_concerns=True, sort="score")
    return [r for r in picks if str(r.get("ticker", "")).upper() not in held][:limit]


def _ideas(screener, held, pos, eligible, now_w, returns, candidate_returns) -> Dict[str, Any]:
    if not screener:
        return {"available": False, "items": [],
                "reason": "The screener hasn't been built yet; it refreshes on the maintenance schedule."}
    from stock_analysis.screener import CAVEAT
    candidate_returns = candidate_returns or {}
    rows = {str(r.get("ticker", "")).upper(): r for r in screener.get("rows") or []}
    held_industries = {rows[t].get("industry") for t in held if t in rows and rows[t].get("industry")}
    # Only an EXIT leaves a hole to fill; a TRIM keeps the position.
    exits = [p["ticker"] for p in pos if p["engine_action"] == "EXIT"]

    port = None
    names = [t for t in eligible if t in returns]
    if names:
        frame = pd.DataFrame({t: returns[t] for t in names}).dropna()
        tot = sum(now_w[t] for t in names)
        if len(frame) >= MIN_OBS and tot > 0:
            port = frame.mul(pd.Series({t: now_w[t] / tot for t in names})).sum(axis=1)

    items = []
    for r in idea_candidates(screener, held):
        t = str(r["ticker"]).upper()
        corr = None
        cr = candidate_returns.get(t)
        if port is not None and cr is not None:
            j = pd.concat([port, cr], axis=1).dropna()
            if len(j) >= MIN_OBS:
                corr = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
        why = [f"fundamentals score {r.get('score'):.0f}" if r.get("score") is not None else None]
        if r.get("industry") and r.get("industry") not in held_industries:
            why.append(f"an industry you don't hold ({r['industry']})")
        if corr is not None and corr < IDEA_DIVERSIFIER_CORR:
            why.append(f"low correlation with your portfolio ({corr:.2f})")
        if exits:
            why.append(f"a possible replacement for {', '.join(exits)}")
        items.append({
            "ticker": t, "name": r.get("name"), "industry": r.get("industry"),
            "score": r.get("score"), "quality_grade": r.get("quality_grade"),
            "pe": _r(r.get("pe"), 1), "fcf_yield_pct": _r((r.get("fcf_yield") or 0) * 100, 1)
            if r.get("fcf_yield") is not None else None,
            "revenue_growth_pct": _r(r["revenue_growth"] * 100, 1) if r.get("revenue_growth") is not None else None,
            "corr_with_portfolio": _r(corr, 2),
            "diversifier": corr is not None and corr < IDEA_DIVERSIFIER_CORR,
            "why": [w for w in why if w],
        })
    # Diversifiers first; the score orders within each group.
    items.sort(key=lambda i: (not i["diversifier"], -(i["score"] or 0)))
    return {"available": True, "items": items[:MAX_IDEAS], "caveat": CAVEAT,
            "generated_at": screener.get("generated_at"), "universe": screener.get("n")}
