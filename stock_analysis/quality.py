"""
Quality of earnings — is the profit real, repeatable, and backed by cash?

Every test here is a published or standard measure with its threshold stated,
computed from the standardized statements (stock_analysis/statements.py), and
returned with its formula and the filing behind every input. Nothing is
fitted; thresholds are the literature's (Beneish 1999, Piotroski 2000,
Altman 1968/1995, Sloan 1996) or plainly stated rules of thumb, labelled as
such.

Each test reports one of:
  GOOD / OK / WATCH / CONCERN   — measured
  NOT_APPLICABLE                — the test is not meaningful for this kind of
                                  company (a bank's operating cash flow), with why
  INSUFFICIENT_DATA             — the filings lack an input, named

The grade weighs only the tests that were measured. A company is never
graded down for a test that could not be run — it is told the test was not run.

Trailing figures (TTM) are compared with the same window a year earlier
(TTM-prior), so a test made on 2024-08-26 uses the four quarters filed by then.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .company import FINANCIAL_KINDS
from .statements import value

GOOD, OK, WATCH, CONCERN = "GOOD", "OK", "WATCH", "CONCERN"
NA, INSUFFICIENT = "NOT_APPLICABLE", "INSUFFICIENT_DATA"
_POINTS = {GOOD: 100.0, OK: 75.0, WATCH: 40.0, CONCERN: 0.0}

# Weight of each test in the grade. Cash-backing and accruals carry the most:
# they are the measures with the longest record of separating earnings that
# persist from earnings that reverse (Sloan 1996).
WEIGHTS = {
    "cash_conversion": 20, "accruals": 15, "beneish": 15, "receivables": 8, "inventory": 7,
    "piotroski": 10, "altman": 5, "stock_comp": 8, "dilution": 5, "one_offs": 4, "revisions": 3,
}


def _inp(block, concept: str, label: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not block:
        return None
    c = (block.get("values") or {}).get(concept)
    if c is None:
        return None
    return {"value": c["value"], "accession": c.get("accession"), "filed": c.get("filed"),
            "period_end": block.get("end"), "derived": c.get("derived", False),
            "label": label or concept}


def _test(key: str, name: str, status: str, value_: Optional[float] = None, display: Optional[str] = None,
          formula: str = "", threshold: str = "", explanation: str = "", inputs: Optional[Dict] = None,
          extra: Optional[Dict] = None) -> Dict[str, Any]:
    t = {"key": key, "name": name, "status": status, "value": value_, "display": display, "formula": formula,
         "threshold": threshold, "explanation": explanation,
         "inputs": {k: v for k, v in (inputs or {}).items() if v is not None}}
    if extra:
        t.update(extra)
    return t


def _missing(key, name, formula, *needed) -> Dict[str, Any]:
    return _test(key, name, INSUFFICIENT, formula=formula,
                 explanation="The filings do not report: " + ", ".join(needed) + ".")


def _na(key, name, why) -> Dict[str, Any]:
    return _test(key, name, NA, explanation=why)


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def _avg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None:
        return b
    if b is None:
        return a
    return (a + b) / 2


# ── Individual tests ────────────────────────────────────────────────────────

def cash_conversion(st, kind) -> Dict[str, Any]:
    key, name = "cash_conversion", "Cash conversion (operating cash flow ÷ net income)"
    if kind in FINANCIAL_KINDS:
        return _na(key, name, "A financial company's operating cash flow moves with its lending and trading "
                              "book, not its earnings — the ratio is not a quality measure for it.")
    t = st.get("ttm")
    ni, ocf, capex = value(t, "net_income"), value(t, "operating_cash_flow"), value(t, "capex")
    if ni is None or ocf is None:
        return _missing(key, name, "OCF / NI", *[n for n, v in (("net income", ni), ("operating cash flow", ocf))
                                                 if v is None])
    # Three fiscal years together smooth timing (a big receivable collected a
    # week after year-end).
    years = st.get("annual", [])[:3]
    ni3 = [value(a, "net_income") for a in years]
    ocf3 = [value(a, "operating_cash_flow") for a in years]
    ratio3 = (sum(ocf3) / sum(ni3)) if len(years) == 3 and all(v is not None for v in ni3 + ocf3) \
        and sum(ni3) > 0 else None
    inputs = {"net_income_ttm": _inp(t, "net_income"), "operating_cash_flow_ttm": _inp(t, "operating_cash_flow"),
              "capex_ttm": _inp(t, "capex")}
    fcf = ocf - capex if capex is not None else None
    if ni <= 0:
        status = WATCH if ocf > 0 else CONCERN
        return _test(key, name, status, None, f"net loss; operating cash flow {'positive' if ocf > 0 else 'negative'}",
                     "OCF / NI (TTM)", "ratio is undefined for a loss; a loss with cash outflow is a concern",
                     "Loss-making: the ratio is not defined. "
                     + ("Operating cash flow is still positive." if ocf > 0 else "Cash is flowing out of operations."),
                     inputs)
    ratio = ocf / ni
    basis = ratio3 if ratio3 is not None else ratio
    status = GOOD if basis >= 1.0 else OK if basis >= 0.8 else WATCH if basis >= 0.5 else CONCERN
    return _test(key, name, status, round(ratio, 3), f"{ratio:.2f}× TTM" + (f", {ratio3:.2f}× over 3 years"
                                                                             if ratio3 is not None else ""),
                 "operating cash flow ÷ net income", "≥1.0 good · 0.8–1.0 ok · 0.5–0.8 watch · <0.5 concern "
                 "(3-year figure used when available)",
                 "Earnings that do not turn into operating cash are made of accruals, which reverse. "
                 + (f"Free cash flow is {fcf / ni:.2f}× net income." if fcf is not None else ""),
                 inputs, {"ratio_3y": None if ratio3 is None else round(ratio3, 3),
                          "fcf_to_net_income": None if fcf is None else round(fcf / ni, 3)})


def accruals(st, kind) -> Dict[str, Any]:
    key, name = "accruals", "Accrual ratio (Sloan)"
    if kind in FINANCIAL_KINDS:
        return _na(key, name, "Accruals are measured against operating cash flow, which is not meaningful "
                              "for a financial company.")
    t, tp = st.get("ttm"), st.get("ttm_prior")
    ni, ocf = value(t, "net_income"), value(t, "operating_cash_flow")
    a1, a0 = value(t, "assets"), value(tp, "assets")
    if ni is None or ocf is None or a1 is None:
        return _missing(key, name, "(NI − OCF) / average assets",
                        *[n for n, v in (("net income", ni), ("operating cash flow", ocf), ("total assets", a1))
                          if v is None])
    avg_assets = _avg(a1, a0)
    r = (ni - ocf) / avg_assets
    status = GOOD if r <= 0 else OK if r <= 0.05 else WATCH if r <= 0.10 else CONCERN
    return _test(key, name, status, round(r, 4), _pct(r), "(net income − operating cash flow) ÷ average total assets",
                 "≤0 good · 0–5% ok · 5–10% watch · >10% concern (Sloan 1996: the highest-accrual decile "
                 "under-performed)",
                 "The share of profit that is accounting accrual rather than cash. High accruals predict "
                 "earnings that fall back.",
                 {"net_income_ttm": _inp(t, "net_income"), "operating_cash_flow_ttm": _inp(t, "operating_cash_flow"),
                  "assets_now": _inp(t, "assets"), "assets_year_ago": _inp(tp, "assets")})


def _period_days(block) -> int:
    from .statements import _days
    return _days(block.get("start"), block.get("end")) or 91


def _days_metric(st, key, name, bal_concept, flow_concept, bal_label, flow_label, explain) -> Dict[str, Any]:
    # A quarter-end balance is measured against that QUARTER's flow and compared
    # with the same quarter a year earlier. Against trailing-year revenue, a
    # surge in the last quarter alone (Exxon, Q2 2026: $116B vs $85B) reads as
    # receivables "outgrowing" sales when they are simply this quarter's sales.
    qs = st.get("quarters") or []
    if len(qs) >= 5 and value(qs[0], bal_concept) is not None and value(qs[0], flow_concept) \
            and value(qs[4], flow_concept):
        t, tp = qs[0], qs[4]
        span1, span0 = _period_days(t), _period_days(tp)
        basis = f"{t['label']} vs {tp['label']}"
    else:
        t, tp = st.get("ttm"), st.get("ttm_prior")
        span1 = span0 = 365
        basis = "trailing year vs the year before"
    b1, b0 = value(t, bal_concept), value(tp, bal_concept)
    f1, f0 = value(t, flow_concept), value(tp, flow_concept)
    if b1 is None or f1 is None or not f1:
        return _missing(key, name, f"{bal_label} ÷ {flow_label} × days",
                        *[n for n, v in ((bal_label, b1), (flow_label, f1)) if v is None])
    d1 = b1 / f1 * span1
    inputs = {f"{bal_concept}_now": _inp(t, bal_concept), f"{flow_concept}_now": _inp(t, flow_concept),
              f"{bal_concept}_year_ago": _inp(tp, bal_concept), f"{flow_concept}_year_ago": _inp(tp, flow_concept)}
    if b0 is None or f0 is None or not f0 or not b0:
        return _test(key, name, OK, round(d1, 1), f"{d1:.0f} days", f"{bal_label} ÷ {flow_label} × days",
                     "needs a year-ago figure to judge the trend", "No year-ago figure to compare.", inputs)
    d0 = b0 / f0 * span0
    bal_g, flow_g = b1 / b0 - 1, f1 / f0 - 1
    gap = bal_g - flow_g
    change = d1 / d0 - 1
    status = (CONCERN if change > 0.30 and gap > 0.20 else WATCH if change > 0.15 and gap > 0.10 else
              GOOD if change < -0.05 else OK)
    return _test(key, name, status, round(d1, 1),
                 f"{d1:.0f} days (was {d0:.0f}); {bal_label} {_pct(bal_g)} vs {flow_label} {_pct(flow_g)}",
                 f"{bal_label} ÷ {flow_label} × days in period ({basis})",
                 "watch: days up >15% and the balance outgrew the flow by >10 pts · concern: >30% and >20 pts",
                 explain, inputs, {"days_year_ago": round(d0, 1), "balance_growth": round(bal_g, 4),
                                   "flow_growth": round(flow_g, 4)})


def receivables(st, kind) -> Dict[str, Any]:
    if kind in FINANCIAL_KINDS:
        return _na("receivables", "Receivables vs sales (DSO)", "Loans are a bank's product, not receivables.")
    return _days_metric(st, "receivables", "Receivables vs sales (DSO)", "receivables", "revenue",
                        "receivables", "revenue",
                        "Receivables growing faster than sales can mean revenue booked before customers pay — "
                        "including sales pulled forward or shipped on generous terms.")


def inventory(st, kind) -> Dict[str, Any]:
    if kind in FINANCIAL_KINDS or kind == "reit":
        return _na("inventory", "Inventory vs cost of sales (DIO)", "No inventory in this business model.")
    if value(st.get("ttm"), "inventory") is None:
        return _na("inventory", "Inventory vs cost of sales (DIO)", "The company reports no inventory.")
    return _days_metric(st, "inventory", "Inventory vs cost of sales (DIO)", "inventory", "cost_of_revenue",
                        "inventory", "cost of sales",
                        "Inventory piling up faster than it sells can precede write-downs, and flatters margins "
                        "while fixed costs are absorbed into stock.")


def beneish(st, kind) -> Dict[str, Any]:
    key, name = "beneish", "Beneish M-score (earnings manipulation risk)"
    if kind in FINANCIAL_KINDS or kind == "reit":
        return _na(key, name, "Beneish's model was estimated on industrial companies; it excludes financials.")
    t, p = st.get("ttm"), st.get("ttm_prior")
    g = lambda b, c: value(b, c)  # noqa: E731
    need = {"revenue": (g(t, "revenue"), g(p, "revenue")), "receivables": (g(t, "receivables"), g(p, "receivables")),
            "assets": (g(t, "assets"), g(p, "assets")), "net_income": (g(t, "net_income"), None),
            "operating_cash_flow": (g(t, "operating_cash_flow"), None)}
    missing = [k for k, (a, b) in need.items() if a is None or (k in ("revenue", "receivables", "assets") and b is None)]
    if missing:
        return _missing(key, name, "M = −4.84 + 0.920·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI "
                                   "− 0.172·SGAI + 4.679·TATA − 0.327·LVGI", *missing)
    s1, s0 = need["revenue"]
    r1, r0 = need["receivables"]
    ta1, ta0 = need["assets"]
    # SGI and TATA have no neutral fallback: undefined inputs make M undefined.
    if s0 <= 0 or s1 <= 0 or ta1 <= 0:
        return _na(key, name, "revenue or total assets is zero or negative in one of the two years — the "
                              "model's ratios are undefined")
    neutral: List[str] = []

    def ratio(fn, label):
        try:
            v = fn()
            if v is None:
                raise ValueError
            return v
        except (TypeError, ValueError, ZeroDivisionError):
            neutral.append(label)
            return 1.0

    dsri = ratio(lambda: (r1 / s1) / (r0 / s0), "DSRI")

    def gm(b):
        rev, cogs, gp = g(b, "revenue"), g(b, "cost_of_revenue"), g(b, "gross_profit")
        if gp is not None and rev:
            return gp / rev
        if cogs is not None and rev:
            return (rev - cogs) / rev
        return None
    gmi = ratio(lambda: gm(p) / gm(t), "GMI")

    def hard(b):
        ca, ppe, ta = g(b, "current_assets"), g(b, "ppe_net"), g(b, "assets")
        return 1 - (ca + ppe) / ta
    aqi = ratio(lambda: hard(t) / hard(p), "AQI")
    sgi = s1 / s0

    def dep_rate(b):
        d, ppe = g(b, "depreciation_amortization"), g(b, "ppe_net")
        return d / (d + ppe)
    depi = ratio(lambda: dep_rate(p) / dep_rate(t), "DEPI")
    sgai = ratio(lambda: (g(t, "sga_expense") / s1) / (g(p, "sga_expense") / s0), "SGAI")

    def lev(b):
        cl, ltd, ta = g(b, "current_liabilities"), g(b, "long_term_debt") or 0.0, g(b, "assets")
        return (cl + ltd) / ta
    lvgi = ratio(lambda: lev(t) / lev(p), "LVGI")
    tata = (need["net_income"][0] - need["operating_cash_flow"][0]) / ta1
    m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
         - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    status = CONCERN if m > -1.78 else WATCH if m > -2.22 else GOOD
    parts = {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi, "DEPI": depi, "SGAI": sgai, "TATA": tata, "LVGI": lvgi}
    drivers = sorted(((k, v) for k, v in parts.items() if k in ("DSRI", "GMI", "AQI", "SGI", "TATA")
                      and ((k == "TATA" and v > 0.05) or (k != "TATA" and v > 1.15))), key=lambda kv: -kv[1])
    return _test(key, name, status, round(m, 3), f"{m:.2f}",
                 "M = −4.84 + 0.920·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI "
                 "+ 4.679·TATA − 0.327·LVGI  (trailing year vs the year before)",
                 "> −1.78 concern (Beneish 1999 cutoff) · −2.22 to −1.78 watch · ≤ −2.22 good",
                 "A probability model of earnings manipulation from eight ratios. A high score is a reason "
                 "to read the filings closely, not evidence of wrongdoing."
                 + (f" Main drivers: {', '.join(f'{k} {v:.2f}' for k, v in drivers)}." if drivers else "")
                 + (f" Set to neutral 1.0 for lack of data: {', '.join(neutral)}." if neutral else ""),
                 {"revenue_ttm": _inp(t, "revenue"), "revenue_prior": _inp(p, "revenue"),
                  "receivables_now": _inp(t, "receivables"), "receivables_prior": _inp(p, "receivables"),
                  "assets_now": _inp(t, "assets"), "net_income_ttm": _inp(t, "net_income"),
                  "operating_cash_flow_ttm": _inp(t, "operating_cash_flow")},
                 {"components": {k: round(v, 4) for k, v in parts.items()}, "neutralized": neutral})


def piotroski(st, kind) -> Dict[str, Any]:
    key, name = "piotroski", "Piotroski F-score (financial strength, 0–9)"
    if kind in FINANCIAL_KINDS:
        return _na(key, name, "Built for industrial companies; its leverage and margin tests don't read a bank.")
    t, p = st.get("ttm"), st.get("ttm_prior")
    g = lambda b, c: value(b, c)  # noqa: E731
    ni, ocf, ta1, ta0 = g(t, "net_income"), g(t, "operating_cash_flow"), g(t, "assets"), g(p, "assets")
    if None in (ni, ocf, ta1, ta0) or g(p, "net_income") is None:
        return _missing(key, name, "nine binary tests", "net income / cash flow / assets for two years")
    tests: Dict[str, Optional[bool]] = {}
    roa1, roa0 = ni / ta0, g(p, "net_income") / ta0
    tests["positive return on assets"] = roa1 > 0
    tests["positive operating cash flow"] = ocf > 0
    tests["return on assets improved"] = roa1 > roa0
    tests["cash flow exceeds net income"] = ocf > ni
    ltd1, ltd0 = g(t, "long_term_debt"), g(p, "long_term_debt")
    tests["long-term debt / assets fell"] = (None if ltd1 is None or ltd0 is None else (ltd1 / ta1) <= (ltd0 / ta0))

    def cur(b):
        ca, cl = g(b, "current_assets"), g(b, "current_liabilities")
        return ca / cl if ca is not None and cl else None
    c1, c0 = cur(t), cur(p)
    tests["current ratio improved"] = None if c1 is None or c0 is None else c1 > c0
    sh1, sh0 = g(t, "shares_diluted"), g(p, "shares_diluted")
    _g = _share_growth(sh1, sh0)
    tests["no new shares issued"] = None if _g is None else _g <= 0.005

    def gm(b):
        rev, gp, cogs = g(b, "revenue"), g(b, "gross_profit"), g(b, "cost_of_revenue")
        if rev and gp is not None:
            return gp / rev
        if rev and cogs is not None:
            return (rev - cogs) / rev
        return None
    m1, m0 = gm(t), gm(p)
    tests["gross margin improved"] = None if m1 is None or m0 is None else m1 > m0
    r1, r0 = g(t, "revenue"), g(p, "revenue")
    tests["asset turnover improved"] = (None if not r1 or not r0 else (r1 / ta1) > (r0 / ta0))
    measured = {k: v for k, v in tests.items() if v is not None}
    score = sum(1 for v in measured.values() if v)
    n = len(measured)
    scaled = score * 9 / n if n else 0
    status = GOOD if scaled >= 7 else OK if scaled >= 5 else WATCH if scaled >= 3 else CONCERN
    return _test(key, name, status, score, f"{score}/{n}" + ("" if n == 9 else f" (of {n} tests measurable)"),
                 "one point each: ROA>0, CFO>0, ΔROA>0, CFO>NI, Δleverage≤0, Δcurrent ratio>0, no dilution, "
                 "Δgross margin>0, Δasset turnover>0",
                 "scaled to 9: ≥7 good · 5–6 ok · 3–4 watch · ≤2 concern (Piotroski 2000: high scorers outperformed)",
                 "Nine plain yes/no checks of profitability, balance-sheet direction and efficiency.",
                 {"net_income_ttm": _inp(t, "net_income"), "operating_cash_flow_ttm": _inp(t, "operating_cash_flow"),
                  "assets_now": _inp(t, "assets"), "assets_year_ago": _inp(p, "assets")},
                 {"tests": tests})


def altman(st, kind, market_cap: Optional[float] = None) -> Dict[str, Any]:
    key, name = "altman", "Altman Z-score (balance-sheet distress)"
    if kind in FINANCIAL_KINDS or kind == "reit":
        return _na(key, name, "Altman's model excludes financial companies and REITs.")
    t = st.get("ttm")
    g = lambda c: value(t, c)  # noqa: E731
    ta, tl, ca, cl, re_ = g("assets"), g("liabilities"), g("current_assets"), g("current_liabilities"), \
        g("retained_earnings")
    ebit = g("operating_income")
    if tl is None and ta is not None and g("equity") is not None:
        tl = ta - g("equity")
    if None in (ta, tl, ca, cl, re_, ebit) or not ta or not tl:
        return _missing(key, name, "Z'' = 6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT/TA + 1.05·BE/TL",
                        *[n for n, v in (("assets", ta), ("liabilities", tl), ("current assets", ca),
                                         ("current liabilities", cl), ("retained earnings", re_),
                                         ("operating income", ebit)) if v is None])
    wc = ca - cl
    sales = g("revenue")
    if kind == "manufacturing" and market_cap and sales:
        z = 1.2 * wc / ta + 1.4 * re_ / ta + 3.3 * ebit / ta + 0.6 * market_cap / tl + 1.0 * sales / ta
        status = GOOD if z > 2.99 else WATCH if z > 1.81 else CONCERN
        formula = "Z = 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MVE/TL + 1.0·Sales/TA (manufacturers, 1968)"
        thr = "> 2.99 safe · 1.81–2.99 grey · < 1.81 distress"
    else:
        be = ta - tl
        z = 6.56 * wc / ta + 3.26 * re_ / ta + 6.72 * ebit / ta + 1.05 * be / tl
        status = GOOD if z > 2.6 else WATCH if z > 1.1 else CONCERN
        formula = "Z'' = 6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT/TA + 1.05·BookEquity/TL (non-manufacturers, 1995)"
        thr = "> 2.6 safe · 1.1–2.6 grey · < 1.1 distress"
    return _test(key, name, status, round(z, 2), f"{z:.2f}", formula, thr,
                 "Bankruptcy-risk score from liquidity, accumulated profits, operating return and leverage. "
                 "Large buybacks drive retained earnings negative and can depress it for healthy companies.",
                 {"assets": _inp(t, "assets"), "liabilities": _inp(t, "liabilities"),
                  "current_assets": _inp(t, "current_assets"), "current_liabilities": _inp(t, "current_liabilities"),
                  "retained_earnings": _inp(t, "retained_earnings"), "operating_income_ttm": _inp(t, "operating_income")})


def stock_comp(st, kind) -> Dict[str, Any]:
    key, name = "stock_comp", "Stock-based compensation"
    t = st.get("ttm")
    sbc, rev, ocf, capex = value(t, "stock_comp"), value(t, "revenue"), value(t, "operating_cash_flow"), \
        value(t, "capex")
    if sbc is None:
        return _missing(key, name, "SBC ÷ revenue; SBC ÷ free cash flow", "stock-based compensation")
    if not rev:
        return _missing(key, name, "SBC ÷ revenue", "revenue")
    to_rev = sbc / rev
    fcf = (ocf - (capex or 0)) if ocf is not None else None
    to_fcf = sbc / fcf if fcf and fcf > 0 else None
    status = (CONCERN if to_rev > 0.15 or (to_fcf is not None and to_fcf > 0.6) else
              WATCH if to_rev > 0.07 or (to_fcf is not None and to_fcf > 0.3) else
              GOOD if to_rev < 0.02 else OK)
    return _test(key, name, status, round(to_rev, 4),
                 f"{_pct(to_rev)} of revenue" + (f", {_pct(to_fcf)} of free cash flow" if to_fcf is not None else ""),
                 "stock-based compensation ÷ revenue; ÷ (operating cash flow − capex)",
                 "rule of thumb: <2% good · >7% of revenue or >30% of FCF watch · >15% or >60% concern",
                 "Stock pay is a real cost that never touches operating cash flow — cash flow looks better "
                 "than the cost of running the business by exactly this amount, paid in dilution instead.",
                 {"stock_comp_ttm": _inp(t, "stock_comp"), "revenue_ttm": _inp(t, "revenue"),
                  "operating_cash_flow_ttm": _inp(t, "operating_cash_flow"), "capex_ttm": _inp(t, "capex")},
                 {"fcf_after_sbc": None if fcf is None else round(fcf - sbc, 0)})


def dilution(st, kind) -> Dict[str, Any]:
    key, name = "dilution", "Share count change"
    years = [a for a in st.get("annual", []) if value(a, "shares_diluted")]
    t, p = st.get("ttm"), st.get("ttm_prior")
    s1, s0 = value(t, "shares_diluted"), value(p, "shares_diluted")
    if s1 is None or s0 is None:
        if len(years) >= 2:
            s1, s0 = value(years[0], "shares_diluted"), value(years[1], "shares_diluted")
        else:
            return _missing(key, name, "diluted shares now ÷ a year ago − 1", "diluted share count history")
    g1 = _share_growth(s1, s0)
    splits = []
    if g1 is None:
        splits.append("trailing year")
        g1 = 0.0
    g3 = None
    if len(years) >= 2:
        steps = []
        for i in range(min(3, len(years) - 1)):
            # Only ADJACENT fiscal years: across a gap (Toyota has no share
            # count for FY2021-22) a 5-for-1 split plus buybacks reads as 4.8×.
            if int(years[i]["label"][2:6]) - int(years[i + 1]["label"][2:6]) != 1:
                break
            g = _share_growth(value(years[i], "shares_diluted"), value(years[i + 1], "shares_diluted"))
            if g is None:
                splits.append(years[i]["label"])
            else:
                steps.append(1 + g)
        if steps:
            prod = 1.0
            for x in steps:
                prod *= x
            g3 = prod ** (1 / len(steps)) - 1
    basis = g3 if g3 is not None else g1
    status = GOOD if basis <= -0.01 else OK if basis <= 0.02 else WATCH if basis <= 0.05 else CONCERN
    if kind == "reit" and status == CONCERN:
        status = WATCH    # REITs fund acquisitions with equity by design; judge per-share cash flow
    return _test(key, name, status, round(g1, 4),
                 f"{_pct(g1)} in a year" + (f", {_pct(g3)}/yr over recent years" if g3 is not None else ""),
                 "weighted diluted shares vs a year earlier (and 3-year annual rate)",
                 "shrinking ≥1%/yr good · up to +2% ok · +2–5% watch · >+5%/yr concern",
                 "Each new share is a smaller slice of the same company; buybacks do the reverse.",
                 {"shares_now": _inp(t, "shares_diluted"), "shares_year_ago": _inp(p, "shares_diluted")},
                 {"annual_rate_3y": None if g3 is None else round(g3, 4),
                  "split_years_excluded": splits})


def _share_growth(s1: Optional[float], s0: Optional[float]) -> Optional[float]:
    """Share-count change, or None when the change is a stock split (a clean
    2×, 3×, 5×… or its inverse) — Toyota's 5-for-1 in 2021 is not dilution."""
    if not s1 or not s0:
        return None
    r = s1 / s0
    big = r if r >= 1 else 1 / r
    if big >= 1.9 and abs(big - round(big)) / big < 0.03:
        return None
    return r - 1


def one_offs(st, kind) -> Dict[str, Any]:
    key, name = "one_offs", "One-off items and tax"
    t = st.get("ttm")
    pti = value(t, "pretax_income")
    if pti is None or pti == 0:
        return _missing(key, name, "(impairments + restructuring − gains + non-operating) ÷ pre-tax income",
                        "pre-tax income")
    imp, rst, gain, nonop = (value(t, "impairment") or 0.0, value(t, "restructuring") or 0.0,
                             value(t, "gain_on_sale") or 0.0, value(t, "nonoperating_income") or 0.0)
    # Pre-tax income minus operating income is everything non-operating, net of
    # interest — the tag alone missed Nvidia's investment gains (~$32B TTM).
    oi = value(t, "operating_income")
    if oi is not None and kind not in FINANCIAL_KINDS:
        nonop = max(nonop, pti - oi)
    tax = value(t, "income_tax")
    etr = tax / pti if tax is not None and pti > 0 else None
    hist = []
    for a in st.get("annual", [])[1:4]:
        pt, tx = value(a, "pretax_income"), value(a, "income_tax")
        if pt and pt > 0 and tx is not None:
            hist.append(tx / pt)
    etr_avg = sum(hist) / len(hist) if hist else None
    gain_share = (gain + max(nonop, 0)) / abs(pti)
    charge_share = (imp + rst) / abs(pti)
    etr_swing = (etr_avg - etr) if etr is not None and etr_avg is not None else None
    notes = []
    status = OK
    if gain_share > 0.25:
        status = WATCH
        notes.append(f"gains and non-operating income are {_pct(gain_share)} of pre-tax income")
    if etr_swing is not None and etr_swing > 0.10:
        status = WATCH
        notes.append(f"tax rate {_pct(etr)} vs {_pct(etr_avg)} average — lower tax is flattering net income")
    if charge_share > 0.25:
        notes.append(f"impairment/restructuring charges are {_pct(charge_share)} of pre-tax income "
                     "(depresses this year; check whether they recur)")
    if status == OK and not notes:
        status = GOOD
    return _test(key, name, status, round(gain_share, 4), "; ".join(notes) or "no large one-offs",
                 "gains + non-operating income vs pre-tax income; effective tax rate vs 3-year average",
                 "watch: gains >25% of pre-tax income, or tax rate >10 pts below its average",
                 "Profit that comes from selling assets, non-operating items or an unusually low tax rate "
                 "is unlikely to repeat.",
                 {"pretax_income_ttm": _inp(t, "pretax_income"), "income_tax_ttm": _inp(t, "income_tax"),
                  "impairment_ttm": _inp(t, "impairment"), "restructuring_ttm": _inp(t, "restructuring"),
                  "gain_on_sale_ttm": _inp(t, "gain_on_sale"), "nonoperating_income_ttm": _inp(t, "nonoperating_income")},
                 {"effective_tax_rate": None if etr is None else round(etr, 4),
                  "effective_tax_rate_3y_avg": None if etr_avg is None else round(etr_avg, 4),
                  "charges_share": round(charge_share, 4)})


def revisions(st, kind) -> Dict[str, Any]:
    key, name = "revisions", "Revisions to previously reported figures"
    as_of = st.get("as_of")
    from .statements import _days, _FY, _in
    material = [r for r in st.get("restatements", []) if r["kind"] == "REVISED"
                and r["concept"] in ("revenue", "net_income", "operating_cash_flow", "operating_income")
                and abs(r["change_pct"]) >= 1.0]
    recent = [r for r in material if (r["revised_filed"] or "") >= _years_before(as_of, 3)]
    annual = [r for r in recent if _in(_days(r["period_start"], r["period_end"]), _FY)]
    big_annual = [r for r in annual if abs(r["change_pct"]) >= 5]
    down = [r for r in big_annual if r["concept"] in ("revenue", "net_income") and r["change_pct"] < 0]
    filings = {r["revised_accession"] for r in recent}
    # Most revisions are re-presentations (discontinued operations, a new
    # accounting standard adopted retrospectively — Tesla's 2025 crypto
    # fair-value change re-filed every 2024 quarter). Only a full year's
    # revenue or profit restated DOWN by 5% or more is a concern on its own.
    status = (GOOD if not recent else CONCERN if down else
              WATCH if big_annual or len(filings) >= 3 else OK)
    return _test(key, name, status, len(recent),
                 (f"{len(recent)} revised figure(s) across {len(filings)} filing(s) in the last 3 years"
                  + (f"; {len(down)} full-year downward revision(s) ≥5%" if down else ""))
                 if recent else "none in the last 3 years",
                 "headline figures (revenue, operating income, net income, operating cash flow) later re-filed "
                 "at a different value, ≥1% change",
                 "none good · re-presentations ok · a full year revised ≥5% or ≥3 revising filings watch · "
                 "full-year revenue or net income revised DOWN ≥5% concern",
                 "Re-filing an earlier figure is usually a re-presentation; a full year's revenue or profit "
                 "restated lower is a correction of what was reported.",
                 {}, {"revisions": recent[:8]})


def _years_before(as_of: Optional[str], n: int) -> str:
    from datetime import date
    d = date.fromisoformat(as_of[:10]) if as_of else date.today()
    return f"{d.year - n}-{d.month:02d}-{d.day:02d}"


# ── Context the grade does not use, but a reader needs ──────────────────────

def returns_and_growth(st) -> Dict[str, Any]:
    t, p = st.get("ttm"), st.get("ttm_prior")
    g = lambda b, c: value(b, c)  # noqa: E731
    out: Dict[str, Any] = {}
    for c in ("revenue", "operating_income", "net_income", "operating_cash_flow"):
        a, b = g(t, c), g(p, c)
        out[f"{c}_growth"] = (a / b - 1) if a is not None and b and b > 0 else None
    rev = g(t, "revenue")
    for c, label in (("gross_profit", "gross_margin"), ("operating_income", "operating_margin"),
                     ("net_income", "net_margin")):
        v = g(t, c)
        if c == "gross_profit" and v is None and rev and g(t, "cost_of_revenue") is not None:
            v = rev - g(t, "cost_of_revenue")
        out[label] = v / rev if v is not None and rev else None
    ni, eq1, eq0 = g(t, "net_income"), g(t, "equity"), g(p, "equity")
    out["return_on_equity"] = ni / _avg(eq1, eq0) if ni is not None and _avg(eq1, eq0) and _avg(eq1, eq0) > 0 else None
    a1, a0 = g(t, "assets"), g(p, "assets")
    out["return_on_assets"] = ni / _avg(a1, a0) if ni is not None and _avg(a1, a0) else None
    oi, tax, pti = g(t, "operating_income"), g(t, "income_tax"), g(t, "pretax_income")
    rate = min(max(tax / pti, 0.0), 0.5) if tax is not None and pti and pti > 0 else 0.21
    debt = (g(t, "long_term_debt") or 0.0) + (g(t, "short_term_debt") or 0.0)
    cash = (g(t, "cash") or 0.0) + (g(t, "short_term_investments") or 0.0)
    invested = (eq1 or 0.0) + debt - cash
    out["roic"] = (oi * (1 - rate) / invested) if oi is not None and eq1 is not None and invested > 0 else None
    ocf, capex = g(t, "operating_cash_flow"), g(t, "capex")
    out["free_cash_flow"] = ocf - (capex or 0.0) if ocf is not None else None
    out["net_debt"] = debt - cash if (g(t, "long_term_debt") is not None or g(t, "short_term_debt") is not None) else None
    return {k: (round(v, 4) if isinstance(v, float) and abs(v) < 1e6 else v) for k, v in out.items()}


def margin_history(st) -> List[Dict[str, Any]]:
    rows = []
    for q in reversed(st.get("quarters", [])[:12]):
        rev = value(q, "revenue")
        if not rev:
            continue
        gp = value(q, "gross_profit")
        if gp is None and value(q, "cost_of_revenue") is not None:
            gp = rev - value(q, "cost_of_revenue")
        oi, ni = value(q, "operating_income"), value(q, "net_income")
        rows.append({"period": q["label"], "end": q["end"],
                     "gross_margin": None if gp is None else round(gp / rev, 4),
                     "operating_margin": None if oi is None else round(oi / rev, 4),
                     "net_margin": None if ni is None else round(ni / rev, 4)})
    return rows


# ── The assessment ──────────────────────────────────────────────────────────

def assess(st: Dict[str, Any], kind: str, market_cap: Optional[float] = None) -> Dict[str, Any]:
    """All tests + a weighted grade over the ones that were measured. Pure."""
    if not st.get("available"):
        return {"available": False, "reason": st.get("reason")}
    tests = [cash_conversion(st, kind), accruals(st, kind), beneish(st, kind), receivables(st, kind),
             inventory(st, kind), piotroski(st, kind), altman(st, kind, market_cap), stock_comp(st, kind),
             dilution(st, kind), one_offs(st, kind), revisions(st, kind)]
    measured = [t for t in tests if t["status"] in _POINTS]
    w = sum(WEIGHTS[t["key"]] for t in measured)
    score = (sum(WEIGHTS[t["key"]] * _POINTS[t["status"]] for t in measured) / w) if w else None
    coverage = w / sum(WEIGHTS.values())
    # A grade from three applicable tests (a bank's) would look as strong as one
    # from eleven. Below half the weight measured, the tests are shown, ungraded.
    graded = score is not None and coverage >= 0.5
    grade = (None if not graded else "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50
             else "D" if score >= 35 else "F")
    flags = [{"test": t["name"], "status": t["status"], "detail": t["display"]}
             for t in tests if t["status"] in (CONCERN, WATCH)]
    flags.sort(key=lambda f: 0 if f["status"] == CONCERN else 1)
    return {
        "available": True, "industry_kind": kind, "score": None if not graded else round(score, 1),
        "grade": grade, "coverage": round(coverage, 3),
        "not_graded_reason": (None if graded else
                              "most earnings-quality tests do not apply to this kind of company "
                              f"({kind}); the applicable ones are shown, not graded"),
        "measured": len(measured), "tests": tests, "flags": flags,
        "context": returns_and_growth(st), "margins": margin_history(st),
        "basis": (st.get("ttm") or {}).get("basis"), "period_end": (st.get("ttm") or {}).get("end"),
        "method": "weighted mean of measured tests: GOOD 100 · OK 75 · WATCH 40 · CONCERN 0; "
                  "weights " + ", ".join(f"{k} {v}" for k, v in WEIGHTS.items()),
    }


def build_quality(symbol: str, as_of: Optional[str] = None, statements: Optional[Dict[str, Any]] = None,
                  profile: Optional[Dict[str, Any]] = None, market_cap: Optional[float] = None) -> Dict[str, Any]:
    from .company import profile as get_profile
    from .statements import build_statements
    st = statements or build_statements(symbol, as_of=as_of)
    prof = profile or get_profile(symbol)
    out = assess(st, prof.get("industry_kind", "unknown"), market_cap)
    out["symbol"] = symbol.upper()
    out["as_of"] = as_of
    return out
