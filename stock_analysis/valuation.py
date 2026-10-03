"""
Valuation — what the price implies, against peers, history and the company's
own cash generation. No price target: a target needs a forecast, and nothing
here forecasts.

  multiples      P/E, EV/Sales, EV/EBIT, P/FCF, P/B, FCF yield, on trailing figures
  history        the same multiples at each past fiscal year-end (price then,
                 figures as filed then), so "expensive" can be measured against
                 the company's own range
  reverse DCF    the constant annual free-cash-flow growth over ten years that
                 today's enterprise value implies, at a STATED discount rate and
                 terminal growth — then compared with the growth the company
                 actually delivered. Assumptions are inputs, printed, never hidden.

Banks and insurers are valued on P/E and P/B only: their debt is raw material,
not financing, so enterprise value means nothing for them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .company import FINANCIAL_KINDS
from .statements import value

DISCOUNT_RATE = 0.09       # stated assumption: a long-run equity return, not a CAPM estimate
TERMINAL_GROWTH = 0.025    # stated assumption: roughly nominal GDP-like long-run growth
YEARS = 10


def multiples(st: Dict[str, Any], mkt: Dict[str, Any], kind: str) -> Dict[str, Any]:
    if not mkt.get("available"):
        return {"available": False, "reason": mkt.get("reason")}
    t = st.get("ttm") or {}
    usd = mkt["fx"]["rate"]
    g = lambda c: (value(t, c) * usd) if value(t, c) is not None else None  # noqa: E731
    mc, ev = mkt["market_cap_usd"], mkt["enterprise_value_usd"]
    rev, ebit, ni, eq = g("revenue"), g("operating_income"), g("net_income"), g("equity")
    ocf, capex = g("operating_cash_flow"), g("capex")
    fcf = ocf - (capex or 0.0) if ocf is not None else None

    def ratio(a, b, positive_only=True):
        if a is None or b is None or b == 0 or (positive_only and b < 0):
            return None
        return a / b
    fin = kind in FINANCIAL_KINDS
    out = {"available": True, "market_cap_usd": mc, "enterprise_value_usd": ev,
           "pe": ratio(mc, ni), "pb": ratio(mc, eq),
           # A bank's operating cash flow moves with its loan book: a "free cash
           # flow yield" of -18% for JPM is arithmetic, not a valuation.
           "fcf_yield": (fcf / mc) if fcf is not None and mc and not fin else None,
           "earnings_yield": (ni / mc) if ni is not None and mc else None}
    if kind not in FINANCIAL_KINDS:
        out.update({"ev_sales": ratio(ev, rev), "ev_ebit": ratio(ev, ebit), "p_fcf": ratio(mc, fcf)})
    else:
        out["note"] = "EV-based multiples are not meaningful for a financial company"
    out["loss_making"] = ni is not None and ni < 0
    out["basis"] = t.get("basis")
    out["figures_end"] = t.get("end")
    out["price_date"] = mkt.get("price_date")
    out["stale_warning"] = staleness(t.get("end"), mkt.get("price_date"))
    return {k: (round(v, 4) if isinstance(v, float) and abs(v) < 1e5 else v) for k, v in out.items()}


def staleness(figures_end: Optional[str], price_date: Optional[str]) -> Optional[str]:
    """A multiple divides today's price by figures that may be well out of date —
    TSMC's latest XBRL year is FY2024 while its price is October 2026. Past 15
    months the mismatch is named on the multiple itself."""
    from .statements import _days
    if not figures_end or not price_date:
        return None
    gap = _days(figures_end, price_date)
    if gap and gap > 456:
        return (f"the latest figures available end {figures_end}, {gap // 30} months before the price "
                f"({price_date}); multiples pair a current price with old results")
    return None


def history(st: Dict[str, Any], symbol: str, kind: str, as_of: Optional[str] = None,
            ads_ratio: float = 1.0, fx_rate: float = 1.0) -> Dict[str, Any]:
    """P/E, EV/Sales, P/FCF at each fiscal year-end, from the price that day
    and the figures for that year."""
    from .market import price_history, splits
    # Both sides on today's split basis: the split-adjusted (not dividend-
    # adjusted) close, and each year's share count scaled by any split after
    # the filing that reported it. Mixing an as-traded price with a later,
    # split-adjusted share count put Nvidia's FY2024 P/E at 511.
    df = price_history(symbol, years=8, as_of=as_of, split_only=True)
    split_list = splits(symbol)
    if df.empty:
        return {"available": False, "reason": "no price history"}
    rows: List[Dict[str, Any]] = []
    for a in (st.get("annual") or [])[:7]:
        end = a["end"]
        px = df[df.index <= end]["Close"]
        from .market import share_count
        found = share_count(a)
        if px.empty or not found or (df.index[0].strftime("%Y-%m-%d") > end):
            continue
        sh, concept, _ = found
        filed = (a["values"].get(concept) or {}).get("filed") or end
        for d, r in split_list:
            if d > filed[:10] and (not as_of or d <= as_of[:10]):
                sh *= r
        mc = float(px.iloc[-1]) * sh / ads_ratio
        g = lambda c: (value(a, c) * fx_rate) if value(a, c) is not None else None  # noqa: E731
        ni, rev = g("net_income"), g("revenue")
        ocf, capex = g("operating_cash_flow"), g("capex")
        debt = (g("long_term_debt") or 0.0) + (g("short_term_debt") or 0.0)
        cash = (g("cash") or 0.0) + (g("short_term_investments") or 0.0)
        fcf = ocf - (capex or 0.0) if ocf is not None else None
        row = {"fiscal_year": a["label"], "end": end, "price_split_adjusted": round(float(px.iloc[-1]), 2),
               "pe": round(mc / ni, 2) if ni and ni > 0 else None,
               "p_fcf": round(mc / fcf, 2) if fcf and fcf > 0 else None}
        if kind not in FINANCIAL_KINDS:
            row["ev_sales"] = round((mc + debt - cash) / rev, 2) if rev else None
        rows.append(row)
    return {"available": bool(rows), "years": rows,
            "note": "FX converted at today's rate for every year (shows the multiple, not currency moves)"
            if fx_rate != 1.0 else None}


def _pv(fcf0: float, g: float, r: float, tg: float, years: int) -> float:
    pv, f = 0.0, fcf0
    for y in range(1, years + 1):
        f *= (1 + g)
        pv += f / (1 + r) ** y
    terminal = f * (1 + tg) / (r - tg)
    return pv + terminal / (1 + r) ** years


def reverse_dcf(ev: float, fcf: float, r: float = DISCOUNT_RATE, tg: float = TERMINAL_GROWTH,
                years: int = YEARS) -> Optional[float]:
    """The constant FCF growth over `years` that makes the DCF equal `ev`."""
    if fcf is None or fcf <= 0 or ev is None or ev <= 0:
        return None
    lo, hi = -0.5, 1.5
    if _pv(fcf, hi, r, tg, years) < ev:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if _pv(fcf, mid, r, tg, years) < ev:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def implied_growth(st: Dict[str, Any], mkt: Dict[str, Any], kind: str) -> Dict[str, Any]:
    if kind in FINANCIAL_KINDS:
        return {"available": False, "reason": "free cash flow is not a meaningful valuation base for a financial"}
    if not mkt.get("available"):
        return {"available": False, "reason": mkt.get("reason")}
    t = st.get("ttm") or {}
    usd = mkt["fx"]["rate"]
    ocf, capex = value(t, "operating_cash_flow"), value(t, "capex")
    if ocf is None:
        return {"available": False, "reason": "no operating cash flow"}
    fcf = (ocf - (capex or 0.0)) * usd
    ev = mkt["enterprise_value_usd"]
    if fcf <= 0:
        return {"available": False, "reason": "free cash flow is negative — there is no cash yield to grow"}
    g = reverse_dcf(ev, fcf)
    sens = {f"{int(r * 100)}%": reverse_dcf(ev, fcf, r=r) for r in (0.08, 0.10)}
    years = st.get("annual") or []
    hist = None
    fcfs = [(value(a, "operating_cash_flow") or 0) - (value(a, "capex") or 0)
            for a in years[:6] if value(a, "operating_cash_flow") is not None]
    if len(fcfs) >= 4 and fcfs[-1] > 0 and fcfs[0] > 0:
        n = len(fcfs) - 1
        hist = (fcfs[0] / fcfs[-1]) ** (1 / n) - 1
    rev_hist = None
    revs = [value(a, "revenue") for a in years[:6] if value(a, "revenue")]
    if len(revs) >= 4 and revs[-1] > 0:
        rev_hist = (revs[0] / revs[-1]) ** (1 / (len(revs) - 1)) - 1
    return {"available": g is not None,
            "implied_fcf_growth": None if g is None else round(g, 4),
            "sensitivity": {k: (None if v is None else round(v, 4)) for k, v in sens.items()},
            "delivered_fcf_growth": None if hist is None else round(hist, 4),
            "delivered_revenue_growth": None if rev_hist is None else round(rev_hist, 4),
            "fcf_ttm_usd": fcf, "enterprise_value_usd": ev,
            "assumptions": {"discount_rate": DISCOUNT_RATE, "terminal_growth": TERMINAL_GROWTH, "years": YEARS},
            "reading": None if g is None else (
                f"Today's value implies free cash flow growing about {100 * g:.1f}% a year for {YEARS} years "
                f"(at a {100 * DISCOUNT_RATE:.0f}% discount rate and {100 * TERMINAL_GROWTH:.1f}% after)"
                + ((f"; it grew {100 * hist:.1f}% a year over the last {len(fcfs) - 1} years." if hist >= 0 else
                    f"; it shrank {100 * -hist:.1f}% a year over the last {len(fcfs) - 1} years.")
                   if hist is not None else ".")),
            "reason": None if g is not None else "implied growth is beyond the solvable range"}
