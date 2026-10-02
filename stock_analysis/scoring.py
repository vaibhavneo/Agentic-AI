"""
The fundamentals pillar score, built from the Stock Analysis Agent's work.

v2 replaces the v1 pillar's four ratio bands, which were computed from "the
latest value of each line item" — for a 10-Q that can divide a nine-month net
income by a three-month revenue, or put one quarter's profit over a year of
equity. v2 uses trailing-twelve-month figures throughout and adds what v1
never saw: earnings quality, growth, the cash return at today's price, and
what the filings themselves disclose.

  quality        the earnings-quality score (stock_analysis/quality.py)    0.30
  profitability  operating margin and return on invested capital           0.25
                 (return on equity for a financial company)
  cash_return    free-cash-flow yield at the price (earnings yield for a   0.20
                 financial company)
  growth         trailing revenue growth                                    0.15
  balance_sheet  debt to equity (not scored for a financial company)        0.10

  minus a filing penalty: 10 points per CONCERN finding (cap 25) and 3 per
  WATCH (cap 9) — a restatement notice, a late filing, a material weakness.

Bands are stated priors, not fitted, in the same spirit as v1's. Weights are
renormalized over the components that could be measured; `coverage` says how
much of the weight that was. No LLM output is read.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .company import FINANCIAL_KINDS

WEIGHTS = {"quality": 0.30, "profitability": 0.25, "cash_return": 0.20, "growth": 0.15, "balance_sheet": 0.10}
CONCERN_PTS, CONCERN_CAP = 10.0, 25.0
WATCH_PTS, WATCH_CAP = 3.0, 9.0
VERSION = "fundamentals-v2"


def _clip(x: float) -> float:
    return max(0.0, min(100.0, x))


def score_components(st: Dict[str, Any], quality: Dict[str, Any], kind: str,
                     market: Optional[Dict[str, Any]] = None,
                     flags: Optional[list] = None) -> Dict[str, Any]:
    """Pure: everything already computed -> the v2 score with its working."""
    from .quality import returns_and_growth
    from .statements import value
    ctx = returns_and_growth(st)
    fin = kind in FINANCIAL_KINDS
    subs: Dict[str, Optional[float]] = {k: None for k in WEIGHTS}
    working: Dict[str, str] = {}

    if quality.get("grade") is not None and quality.get("score") is not None:
        subs["quality"] = float(quality["score"])
        working["quality"] = f"earnings-quality score {quality['score']} (grade {quality['grade']})"

    if fin:
        roe = ctx.get("return_on_equity")
        if roe is not None:
            subs["profitability"] = _clip(roe * 400.0)                       # 25% ROE -> 100
            working["profitability"] = f"ROE {100 * roe:.1f}% × 400"
    else:
        parts = []
        om, roic = ctx.get("operating_margin"), ctx.get("roic")
        if om is not None:
            parts.append(_clip(om * 300.0))                                  # 33% margin -> 100
        if roic is not None:
            parts.append(_clip(roic * 300.0))                                # 33% ROIC -> 100
        if parts:
            subs["profitability"] = sum(parts) / len(parts)
            working["profitability"] = ("mean(operating margin × 300, ROIC × 300): "
                                        f"{'—' if om is None else f'{100 * om:.1f}%'}, "
                                        f"{'—' if roic is None else f'{100 * roic:.1f}%'}")

    g = ctx.get("revenue_growth")
    if g is not None:
        subs["growth"] = _clip(50.0 + g * 250.0)                             # ±20% -> 100/0
        working["growth"] = f"50 + revenue growth {100 * g:.1f}% × 250"

    if market and market.get("available"):
        t = st.get("ttm") or {}
        usd = market["fx"]["rate"]
        mc = market["market_cap_usd"]
        if fin:
            ni = value(t, "net_income")
            if ni is not None and mc:
                ey = ni * usd / mc
                subs["cash_return"] = _clip(ey * 800.0)                       # 12.5% -> 100
                working["cash_return"] = f"earnings yield {100 * ey:.1f}% × 800"
        else:
            ocf, capex = value(t, "operating_cash_flow"), value(t, "capex")
            if ocf is not None and mc:
                fy = (ocf - (capex or 0.0)) * usd / mc
                subs["cash_return"] = _clip(30.0 + fy * 1000.0)              # 0% -> 30, 7% -> 100
                working["cash_return"] = f"30 + FCF yield {100 * fy:.1f}% × 1000"

    if not fin:
        t = st.get("ttm") or {}
        eq = value(t, "equity")
        debt = (value(t, "long_term_debt") or 0.0) + (value(t, "short_term_debt") or 0.0)
        if eq and eq > 0 and (value(t, "long_term_debt") is not None or value(t, "short_term_debt") is not None):
            de = debt / eq
            subs["balance_sheet"] = _clip(100.0 - de * 33.3)                 # 0 -> 100, 3x -> 0
            working["balance_sheet"] = f"100 − debt/equity {de:.2f} × 33.3"
        elif eq is not None and eq <= 0:
            subs["balance_sheet"] = 20.0
            working["balance_sheet"] = "negative equity (often from buybacks): scored 20"

    measured = {k: v for k, v in subs.items() if v is not None}
    w = sum(WEIGHTS[k] for k in measured)
    base = sum(WEIGHTS[k] * v for k, v in measured.items()) / w if w else None

    concerns = [f for f in (flags or []) if f.get("severity") == "CONCERN"]
    watches = [f for f in (flags or []) if f.get("severity") == "WATCH"]
    penalty = min(CONCERN_CAP, CONCERN_PTS * len(concerns)) + min(WATCH_CAP, WATCH_PTS * len(watches))
    score = None if base is None else round(_clip(base - penalty), 1)
    return {"version": VERSION, "score": score, "base": None if base is None else round(base, 1),
            "penalty": penalty, "coverage": round(w, 3), "subs": {k: (None if v is None else round(v, 1))
                                                                   for k, v in subs.items()},
            "working": working, "weights": WEIGHTS,
            "penalized_findings": [f"{f['severity']}: {f.get('title')}" for f in concerns + watches][:10]}


def fundamental_score(symbol: str, as_of: Optional[str] = None, price: Optional[float] = None,
                      read_text: bool = True) -> Dict[str, Any]:
    """Live entry point: build what the score needs and score it. Never raises."""
    try:
        from .company import profile as get_profile
        from .filings import review, filing_index, index_flags, _annual_text, ANNUAL
        from .market import market_inputs
        from .quality import assess
        from .statements import build_statements
        st = build_statements(symbol, as_of=as_of)
        if not st.get("available"):
            return {"available": False, "reason": st.get("reason"), "version": VERSION}
        prof = get_profile(symbol)
        kind = prof.get("industry_kind", "unknown")
        q = assess(st, kind)
        if read_text:
            rev = review(symbol, as_of)
            flags = rev.get("flags") or []
            annual = rev.get("latest_annual")
        else:
            idx = filing_index(symbol, as_of)["filings"]
            flags, _ = index_flags(idx, as_of)
            annual = next((f for f in idx if f["form"] in ANNUAL), None)
        text = _annual_text(symbol, annual) if (st.get("filer") or {}).get("is_foreign") and annual else None
        mkt = market_inputs(symbol, st, as_of, annual_text=text, price=price)
        out = score_components(st, q, kind, mkt, flags)
        out.update({"available": out["score"] is not None, "symbol": symbol.upper(), "as_of": as_of,
                    "industry_kind": kind, "period_end": (st.get("ttm") or {}).get("end"),
                    "quality_grade": q.get("grade"), "market_available": bool(mkt.get("available")),
                    "source": "sec-edgar"})
        return out
    except Exception as e:
        return {"available": False, "reason": f"{type(e).__name__}: {e}", "version": VERSION}
