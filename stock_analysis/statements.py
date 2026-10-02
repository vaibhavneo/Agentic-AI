"""
Standardized financial statements, built from what a company actually filed.

Every number here comes from an SEC XBRL fact (10-K / 10-Q, or 20-F / 40-F
for foreign issuers) fetched through the FinancialDataGateway, and keeps the
accession number of the filing it came from. Three things this module has to
get right, each of which silently corrupts every ratio built on top if missed:

  1. QUARTERS ARE MOSTLY NOT FILED. A 10-Q reports a 3-month income statement
     but a YEAR-TO-DATE cash flow statement, and the 10-K reports only the full
     year. Q4 never appears anywhere; Q2 operating cash flow never appears
     anywhere. Both are derived — Q4 = FY − 9M, Q2 = 6M − 3M — and every derived
     cell says so (`derived: True`, `how`), so a reader can tell a reported
     number from arithmetic.

  2. A FILING REPORTS SEVERAL PERIODS THAT END ON THE SAME DAY. Q3's 10-Q has a
     3-month and a 9-month revenue, both ending on the quarter end. Collapsing
     facts by period END (as the gateway's generic collapse does) mixes them;
     here a period is (start, end), always.

  3. POINT IN TIME. `as_of` is passed to the gateway, which drops every fact
     filed after it. Restatements are resolved only among the survivors — the
     latest value filed on or before `as_of` is the one a reader then saw — and
     earlier differing values are kept in `restatements`, because a company
     that keeps revising last year's numbers is itself a finding.

Foreign private issuers file annual reports only (their half-year 6-K is not
XBRL), so their trailing figures are the latest fiscal year and say so. Their
statements are in the reporting currency (TWD for TSMC, EUR for ASML) and the
currency is carried on every response; nothing here converts it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

# ── What each line item is ──────────────────────────────────────────────────

FLOW = {
    "revenue", "cost_of_revenue", "gross_profit", "operating_expenses", "rd_expense", "sga_expense",
    "operating_income", "interest_expense", "nonoperating_income", "pretax_income", "income_tax",
    "net_income", "net_income_continuing", "depreciation_amortization", "stock_comp", "impairment",
    "restructuring", "gain_on_sale", "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
    "capex", "capitalized_software", "acquisitions", "buybacks", "dividends_paid", "debt_issued",
    "debt_repaid", "income_taxes_paid", "interest_paid",
}
# Weighted-average share counts and EPS span a period but do not ADD across
# quarters, so they are never derived by subtraction.
DURATION_NON_ADDITIVE = {"eps_basic", "eps_diluted", "shares_basic", "shares_diluted"}
INSTANT = {
    "assets", "liabilities", "equity", "cash", "short_term_investments", "receivables", "inventory",
    "current_assets", "ppe_net", "goodwill", "intangibles", "accounts_payable", "current_liabilities",
    "deferred_revenue", "short_term_debt", "long_term_debt", "retained_earnings",
    "operating_lease_liabilities", "shares_outstanding", "shares_outstanding_cover", "public_float",
}
ALL = sorted(FLOW | DURATION_NON_ADDITIVE | INSTANT)

LABELS = {
    "revenue": "Revenue", "cost_of_revenue": "Cost of revenue", "gross_profit": "Gross profit",
    "operating_expenses": "Operating expenses", "rd_expense": "R&D", "sga_expense": "SG&A",
    "operating_income": "Operating income", "interest_expense": "Interest expense",
    "nonoperating_income": "Non-operating income", "pretax_income": "Pre-tax income",
    "income_tax": "Income tax", "net_income": "Net income",
    "net_income_continuing": "Net income (continuing ops)", "eps_basic": "EPS (basic)",
    "eps_diluted": "EPS (diluted)", "shares_basic": "Weighted shares (basic)",
    "shares_diluted": "Weighted shares (diluted)", "depreciation_amortization": "Depreciation & amortization",
    "stock_comp": "Stock-based compensation", "impairment": "Impairments", "restructuring": "Restructuring",
    "gain_on_sale": "Gain (loss) on asset sales", "operating_cash_flow": "Operating cash flow",
    "investing_cash_flow": "Investing cash flow", "financing_cash_flow": "Financing cash flow",
    "capex": "Capital expenditure", "capitalized_software": "Capitalized software",
    "acquisitions": "Acquisitions", "buybacks": "Share buybacks", "dividends_paid": "Dividends paid",
    "debt_issued": "Debt issued", "debt_repaid": "Debt repaid", "income_taxes_paid": "Income taxes paid",
    "interest_paid": "Interest paid", "assets": "Total assets", "liabilities": "Total liabilities",
    "equity": "Shareholders' equity", "cash": "Cash & equivalents",
    "short_term_investments": "Short-term investments", "receivables": "Receivables",
    "inventory": "Inventory", "current_assets": "Current assets", "ppe_net": "PP&E (net)",
    "goodwill": "Goodwill", "intangibles": "Intangibles", "accounts_payable": "Accounts payable",
    "current_liabilities": "Current liabilities", "deferred_revenue": "Deferred revenue",
    "short_term_debt": "Short-term debt", "long_term_debt": "Long-term debt",
    "retained_earnings": "Retained earnings", "operating_lease_liabilities": "Operating lease liabilities",
    "shares_outstanding": "Shares outstanding", "shares_outstanding_cover": "Shares outstanding (cover page)",
    "public_float": "Public float",
}

STATEMENT_LAYOUT = {
    "income_statement": ["revenue", "cost_of_revenue", "gross_profit", "rd_expense", "sga_expense",
                         "operating_expenses", "operating_income", "interest_expense", "nonoperating_income",
                         "pretax_income", "income_tax", "net_income", "eps_diluted", "shares_diluted",
                         "stock_comp", "depreciation_amortization", "impairment", "restructuring"],
    "balance_sheet": ["cash", "short_term_investments", "receivables", "inventory", "current_assets",
                      "ppe_net", "goodwill", "intangibles", "assets", "accounts_payable", "deferred_revenue",
                      "short_term_debt", "current_liabilities", "long_term_debt", "operating_lease_liabilities",
                      "liabilities", "retained_earnings", "equity", "shares_outstanding"],
    "cash_flow": ["operating_cash_flow", "capex", "capitalized_software", "acquisitions", "investing_cash_flow",
                  "buybacks", "dividends_paid", "debt_issued", "debt_repaid", "financing_cash_flow",
                  "income_taxes_paid", "interest_paid"],
}

# Duration bands in days. A fiscal "quarter" of a 52/53-week year runs 84-98.
_Q = (80, 100)
_H = (170, 195)
_9M = (260, 290)
_FY = (350, 380)
_RESTATE_TOLERANCE = 0.005     # 0.5% — rounding in a later comparative isn't a restatement

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT", "10-KT/A"}
# Only financial-statement filings count. Proxy statements (DEF 14A) now
# carry XBRL "pay versus performance" tables that include company net income;
# filed after the 10-K, they would otherwise win as the "latest" value.
STATEMENT_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A"}


def _d(s: Optional[str]) -> Optional[date]:
    return datetime.strptime(s[:10], "%Y-%m-%d").date() if s else None


def _days(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    return (_d(end) - _d(start)).days + 1


def _in(n: Optional[int], band: Tuple[int, int]) -> bool:
    return n is not None and band[0] <= n <= band[1]


# ── Loading and collapsing facts ────────────────────────────────────────────

def _currency(facts: List[Dict[str, Any]]) -> Optional[str]:
    """The reporting currency: the monetary unit most of the headline facts
    use. TSMC tags some figures in USD as a convenience translation; its books
    are in TWD, and mixing the two would be off by a factor of thirty."""
    counts: Dict[str, int] = defaultdict(int)
    for f in facts:
        if f["concept"] in ("revenue", "assets", "net_income", "equity") and "/" not in f["unit"] \
                and f["unit"] not in ("shares", "pure"):
            counts[f["unit"]] += 1
    if not counts:
        return None
    return max(counts, key=lambda u: (counts[u], u == "USD"))


def _wanted_unit(concept: str, unit: str, currency: Optional[str]) -> bool:
    if concept in ("shares_basic", "shares_diluted", "shares_outstanding", "shares_outstanding_cover"):
        return unit == "shares"
    if concept in ("eps_basic", "eps_diluted"):
        return unit == f"{currency}/shares"
    return unit == currency


def collapse(facts: List[Dict[str, Any]]) -> Tuple[Dict[Tuple, Dict[str, Any]], List[Dict[str, Any]]]:
    """(concept, start, end) -> the latest-filed fact; plus every case where an
    earlier filing reported a materially different value for the same period."""
    groups: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
    for f in facts:
        groups[(f["concept"], f["start"], f["end"])].append(f)
    # The tag is chosen per period among what survived the point-in-time cut:
    # the highest-priority tag on file for that period, then its latest filing.
    for key, fs in list(groups.items()):
        best = min(f.get("tag_rank") or 0 for f in fs)
        groups[key] = [f for f in fs if (f.get("tag_rank") or 0) == best]
    current: Dict[Tuple, Dict[str, Any]] = {}
    restatements: List[Dict[str, Any]] = []
    for key, fs in groups.items():
        fs.sort(key=lambda x: (x["filed"], x["accession"] or ""))
        latest = fs[-1]
        current[key] = latest
        first = fs[0]
        base = abs(first["value"]) or 1.0
        if abs(latest["value"] - first["value"]) / base > _RESTATE_TOLERANCE and \
                abs(latest["value"] - first["value"]) > 0.001:
            restatements.append({
                "kind": _revision_kind(key[0], first["value"], latest["value"]),
                "concept": key[0], "period_start": key[1], "period_end": key[2],
                "original": first["value"], "original_filed": first["filed"], "original_form": first["form"],
                "original_accession": first["accession"],
                "revised": latest["value"], "revised_filed": latest["filed"], "revised_form": latest["form"],
                "revised_accession": latest["accession"],
                "change_pct": round(100 * (latest["value"] - first["value"]) / base, 2),
            })
    return current, restatements


_SHARE_BASED = {"eps_basic", "eps_diluted", "shares_basic", "shares_diluted", "shares_outstanding",
                "shares_outstanding_cover"}


def _revision_kind(concept: str, original: float, revised: float) -> str:
    """A 4-for-1 split rescales every past EPS and share count by exactly 4.
    That is a SPLIT_ADJUSTMENT, not a company revising what it earned."""
    if concept in _SHARE_BASED and original and revised:
        r = abs(revised / original)
        r = r if r >= 1 else 1 / r
        # EPS is printed to the cent, so a 10-for-1 split turns $1.76 into
        # $0.17 — a ratio of 10.35, not 10. Share counts are exact.
        tol = 0.08 if concept.startswith("eps") else 0.02
        if r >= 1.9 and abs(r - round(r)) / r < tol:
            return "SPLIT_ADJUSTMENT"
    return "REVISED"


def _cell(f: Dict[str, Any], derived: bool = False, how: Optional[str] = None,
          sources: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    c = {"value": f["value"], "accession": f.get("accession"), "filed": f.get("filed"),
         "form": f.get("form"), "tag": f.get("tag"), "derived": derived}
    if how:
        c["how"] = how
    if sources:
        c["inputs"] = [{"accession": s.get("accession"), "filed": s.get("filed"), "start": s.get("start"),
                        "end": s.get("end"), "value": s.get("value")} for s in sources]
        c["accession"] = sources[-1].get("accession")
        c["filed"] = max(s.get("filed") or "" for s in sources)
    return c


# ── Fiscal calendar ─────────────────────────────────────────────────────────

def _fiscal_years(current: Dict[Tuple, Dict[str, Any]],
                  annual_periods: Optional[set] = None) -> List[Tuple[str, str]]:
    """(start, end) of every fiscal year an ANNUAL report covered. A 10-Q's
    trailing-twelve-month cash flow (Amazon prints one) is a year long but is
    not a fiscal year; treating it as one invented an "FY2026" ending in June."""
    years = set()
    for (concept, start, end), f in current.items():
        if concept in FLOW and _in(_days(start, end), _FY) and \
                (annual_periods is None or (start, end) in annual_periods):
            years.add((start, end))
    # Two concepts can disagree on the FY start by a day or two (52/53-week
    # years); keep one per fiscal-year end.
    by_end: Dict[str, Tuple[str, str]] = {}
    for s, e in sorted(years):
        k = e[:7]
        if k not in by_end or s < by_end[k][0]:
            by_end[k] = (s, e)
    return sorted(by_end.values(), key=lambda x: x[1])


def _near(a: str, b: str, tol: int = 6) -> bool:
    return abs((_d(a) - _d(b)).days) <= tol


def _quarter_ends(current: Dict[Tuple, Dict[str, Any]], fy: Tuple[str, str]) -> List[str]:
    """The four quarter-end dates of one fiscal year, from every flow fact that
    starts at the FY start (a year-to-date figure) or is itself a quarter."""
    fy_start, fy_end = fy
    ends: List[str] = []
    for (concept, start, end) in current:
        if concept not in FLOW or not start or not end:
            continue
        if not (fy_start <= end <= fy_end) or start < fy_start:
            continue
        n = _days(start, end)
        if (start == fy_start and (_in(n, _Q) or _in(n, _H) or _in(n, _9M))) or _in(n, _Q):
            ends.append(end)
    ends.append(fy_end)
    out: List[str] = []
    for e in sorted(set(ends)):
        if not out or not _near(out[-1], e, 20):
            out.append(e)
        else:
            out[-1] = max(out[-1], e) if e == fy_end else out[-1]
    # Expect ~91, 182, 273, 364 days in; drop anything that isn't a quarter end.
    keep = []
    for e in out:
        n = _days(fy_start, e)
        if any(abs(n - t) <= 12 for t in (91, 182, 273)) or e == fy_end:
            keep.append(e)
    return keep[-4:]


def _find(current, concept: str, start: Optional[str], end: str, tol: int = 6) -> Optional[Dict[str, Any]]:
    f = current.get((concept, start, end))
    if f is not None:
        return f
    for (c, s, e), v in current.items():
        if c != concept or not e or not _near(e, end, tol):
            continue
        if start is None and s is None:
            return v
        if start is not None and s is not None and _near(s, start, tol):
            return v
    return None


def _quarter_flows(current, concept: str, fy: Tuple[str, str], ends: List[str]) -> List[Optional[Dict[str, Any]]]:
    """Discrete value for each quarter of the fiscal year: reported when a
    3-month figure exists, else the difference of consecutive year-to-date
    figures (which is how Q4 and most cash-flow quarters come to exist)."""
    fy_start = fy[0]
    out: List[Optional[Dict[str, Any]]] = []
    prev_end: Optional[str] = None
    prev_ytd: Optional[Dict[str, Any]] = None
    for i, end in enumerate(ends):
        q_start = fy_start if i == 0 else None
        direct = None
        for (c, s, e), f in current.items():
            if c == concept and e and _near(e, end) and _in(_days(s, e), _Q) and \
                    (i == 0 or (prev_end and s and _d(s) > _d(prev_end))):
                direct = f
                break
        ytd = _find(current, concept, fy_start, end)
        if direct is not None:
            out.append(_cell(direct))
        elif i == 0 and ytd is not None:
            out.append(_cell(ytd))
        elif ytd is not None and prev_ytd is not None:
            v = dict(ytd)
            v["value"] = ytd["value"] - prev_ytd["value"]
            label = "full year" if end == fy[1] else "year-to-date"
            out.append(_cell(v, derived=True,
                             how=f"{label} to {ytd['end']} minus year-to-date to {prev_ytd['end']}",
                             sources=[prev_ytd, ytd]))
        elif ytd is not None and i > 0 and all(o is not None for o in out):
            # No previous YTD figure, but every earlier quarter is known.
            v = dict(ytd)
            v["value"] = ytd["value"] - sum(o["value"] for o in out)
            out.append(_cell(v, derived=True,
                             how=f"year-to-date to {ytd['end']} minus the {i} earlier quarters"))
        else:
            out.append(None)
        if ytd is not None:
            prev_ytd = ytd
        elif direct is not None and prev_ytd is not None and out[-1] is not None:
            synth = dict(direct)
            synth["value"] = prev_ytd["value"] + direct["value"]
            synth["end"] = direct["end"]
            prev_ytd = synth
        elif direct is not None and i == 0:
            prev_ytd = direct
        prev_end = end
        _ = q_start
    return out


# ── Public API ──────────────────────────────────────────────────────────────

def load_facts(symbol: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """Every PIT-visible XBRL fact for the statement concepts, normalized."""
    from financial_data import gateway as gw
    res = gw.get("fundamentals_pit", symbol, as_of=as_of, concepts=ALL, collapse_restatements=False,
                 all_tags=True)
    facts = []
    for d in res["data"]:
        try:
            val = float(d["value"])
        except (TypeError, ValueError):
            continue
        ex = d.get("extra") or {}
        if ex.get("form") not in STATEMENT_FORMS:
            continue
        facts.append({
            "concept": d["concept"], "value": val, "unit": d.get("unit") or "",
            "start": d.get("period_start"), "end": d.get("period_end"),
            "filed": str(d["available_at"])[:10], "accession": (d.get("source") or {}).get("document"),
            "tag": (d.get("source") or {}).get("ref"), "form": ex.get("form"), "fy": ex.get("fy"),
            "fp": ex.get("fp"), "tag_rank": ex.get("tag_rank") or 0,
        })
    return {"facts": facts, "as_of_honored": res.get("as_of_honored", False),
            "unavailable": res.get("unavailable") or [], "warnings": res.get("warnings") or [],
            "provider": res.get("provider")}


def build_from_facts(symbol: str, facts: List[Dict[str, Any]], as_of: Optional[str] = None,
                     n_quarters: int = 20, n_years: int = 10) -> Dict[str, Any]:
    """Pure: normalized facts -> standardized statements. Offline-testable."""
    out: Dict[str, Any] = {"symbol": symbol.upper(), "available": False, "as_of": as_of, "warnings": []}
    currency = _currency(facts)
    if not currency:
        out["reason"] = "no revenue, assets, net income or equity facts in any currency"
        return out
    facts = [f for f in facts if _wanted_unit(f["concept"], f["unit"], currency)]
    if not facts:
        out["reason"] = "no facts in the reporting currency"
        return out

    taxonomy = "ifrs-full" if any((f.get("tag") or "").startswith("ifrs-full") for f in facts
                                   if f["concept"] in ("revenue", "assets")) else "us-gaap"
    annual_forms = sorted({f["form"] for f in facts if f.get("form") in ANNUAL_FORMS})
    has_10q = any((f.get("form") or "").startswith("10-Q") for f in facts)
    form_type = ("20-F" if any(fm.startswith("20-F") for fm in annual_forms) else
                 "40-F" if any(fm.startswith("40-F") for fm in annual_forms) else "10-K")

    current, restatements = collapse(facts)
    annual_periods = {(f["start"], f["end"]) for f in facts
                      if f.get("form") in ANNUAL_FORMS and f["concept"] in FLOW}
    years = _fiscal_years(current, annual_periods)
    if not years:
        out["reason"] = "no full-year flow figures — cannot place a fiscal calendar"
        return out

    # ── annual ──
    annual = []
    for fy in years:
        vals: Dict[str, Any] = {}
        for c in FLOW | DURATION_NON_ADDITIVE:
            f = _find(current, c, fy[0], fy[1])
            if f is not None and _in(_days(f["start"], f["end"]), _FY):
                vals[c] = _cell(f)
        for c in INSTANT:
            f = _find(current, c, None, fy[1])
            if f is not None:
                vals[c] = _cell(f)
        annual.append({"label": f"FY{fy[1][:4]}", "start": fy[0], "end": fy[1], "values": vals})

    # ── quarterly (domestic filers) ──
    quarters: List[Dict[str, Any]] = []
    if has_10q:
        for fy in years[-(n_quarters // 4 + 2):]:
            ends = _quarter_ends(current, fy)
            if len(ends) != 4:
                out["warnings"].append(f"FY ending {fy[1]}: found {len(ends)} quarter ends, expected 4")
                continue
            per_concept = {c: _quarter_flows(current, c, fy, ends) for c in FLOW}
            for i, end in enumerate(ends):
                start = fy[0] if i == 0 else ends[i - 1]
                vals = {}
                for c in FLOW:
                    cell = per_concept[c][i]
                    if cell is not None:
                        vals[c] = cell
                for c in DURATION_NON_ADDITIVE:
                    for (cc, s, e), f in current.items():
                        if cc == c and e and _near(e, end) and _in(_days(s, e), _Q):
                            vals[c] = _cell(f)
                            break
                for c in INSTANT:
                    f = _find(current, c, None, end)
                    if f is not None:
                        vals[c] = _cell(f)
                quarters.append({"label": f"FY{fy[1][:4]} Q{i + 1}", "start": start, "end": end,
                                 "fiscal_year_end": fy[1], "values": vals})
        # A fiscal year still in progress has quarters but no FY figure yet.
        last_fy_end = years[-1][1]
        quarters.extend(_open_year_quarters(current, last_fy_end, years[-1]))

    quarters.sort(key=lambda q: q["end"])
    annual.sort(key=lambda a: a["end"])

    ttm, ttm_prior = _ttm(quarters, annual, form_type)
    filed_dates = sorted({f["filed"] for f in facts})
    latest_annual = next((f for f in sorted(facts, key=lambda x: x["filed"], reverse=True)
                          if f.get("form") in ANNUAL_FORMS), None)

    out.update({
        "available": True,
        "filer": {"form_type": form_type, "taxonomy": taxonomy, "currency": currency,
                  "annual_only": not has_10q, "is_foreign": form_type in ("20-F", "40-F")},
        "quarters": list(reversed(quarters[-n_quarters:])),
        "annual": list(reversed(annual[-n_years:])),
        "ttm": ttm, "ttm_prior": ttm_prior,
        "restatements": sorted(restatements, key=lambda r: r["revised_filed"], reverse=True),
        "latest_filed": filed_dates[-1] if filed_dates else None,
        "latest_annual_report": ({"form": latest_annual["form"], "filed": latest_annual["filed"],
                                  "accession": latest_annual["accession"]} if latest_annual else None),
        "coverage": {c: sum(1 for a in annual if c in a["values"]) for c in ALL},
        "layout": STATEMENT_LAYOUT, "labels": LABELS,
    })
    if not has_10q:
        out["warnings"].append(f"{form_type} filer: annual figures only — interim reports are not XBRL-tagged, "
                               "so trailing figures are the latest fiscal year")
    return out


def _open_year_quarters(current, last_fy_end: str, last_fy: Tuple[str, str]) -> List[Dict[str, Any]]:
    """Quarters of the fiscal year after the last completed one."""
    out = []
    next_start = None
    for (c, s, e) in current:
        if c in FLOW and s and e and s > last_fy_end and _days(last_fy_end, s) <= 10:
            if next_start is None or s < next_start:
                next_start = s
    if not next_start:
        return out
    fy_len = _days(*last_fy)
    synthetic_fy = (next_start, (_d(next_start).fromordinal(_d(next_start).toordinal() + fy_len - 1)).isoformat())
    ends = []
    for (c, s, e) in current:
        if c in FLOW and s == next_start and e and (_in(_days(s, e), _Q) or _in(_days(s, e), _H)
                                                     or _in(_days(s, e), _9M)):
            ends.append(e)
    clustered: List[str] = []
    for e in sorted(set(ends)):
        if not clustered or not _near(clustered[-1], e, 20):
            clustered.append(e)
    per_concept = {c: _quarter_flows(current, c, synthetic_fy, clustered) for c in FLOW}
    for i, end in enumerate(clustered):
        vals = {}
        for c in FLOW:
            cell = per_concept[c][i]
            if cell is not None:
                vals[c] = cell
        for c in DURATION_NON_ADDITIVE:
            for (cc, s, e), f in current.items():
                if cc == c and e and _near(e, end) and _in(_days(s, e), _Q):
                    vals[c] = _cell(f)
                    break
        for c in INSTANT:
            f = _find(current, c, None, end)
            if f is not None:
                vals[c] = _cell(f)
        out.append({"label": f"FY{synthetic_fy[1][:4]} Q{i + 1}", "start": next_start if i == 0 else clustered[i - 1],
                    "end": end, "fiscal_year_end": synthetic_fy[1], "values": vals, "fiscal_year_open": True})
    return out


def _ttm(quarters: List[Dict[str, Any]], annual: List[Dict[str, Any]], form_type: str):
    """Trailing twelve months: the last four discrete quarters summed, when all
    four exist and are contiguous; otherwise the latest fiscal year, labelled."""
    def block(qs: List[Dict[str, Any]], fallback: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not qs and not fallback:
            return None
        vals, method = {}, {}
        end = qs[-1]["end"] if qs else fallback["end"]
        for c in FLOW:
            cells = [q["values"].get(c) for q in qs] if len(qs) == 4 else []
            if cells and all(cells):
                vals[c] = {"value": sum(x["value"] for x in cells), "derived": True,
                           "how": "sum of the last four quarters",
                           "accession": cells[-1].get("accession"), "filed": max(x.get("filed") or "" for x in cells),
                           "quarters": [q["label"] for q in qs]}
                method[c] = "4Q"
            elif fallback and c in fallback["values"]:
                vals[c] = dict(fallback["values"][c])
                method[c] = f"FY ({fallback['label']})"
        for c in ("shares_diluted", "shares_basic"):
            cells = [q["values"].get(c) for q in qs if q["values"].get(c)]
            if cells:
                vals[c] = {"value": sum(x["value"] for x in cells) / len(cells), "derived": True,
                           "how": f"average of {len(cells)} quarterly weighted counts",
                           "accession": cells[-1].get("accession"), "filed": cells[-1].get("filed")}
                method[c] = "avg"
            elif fallback and c in fallback["values"]:
                vals[c] = dict(fallback["values"][c])
                method[c] = f"FY ({fallback['label']})"
        latest_bs = qs[-1] if qs else fallback
        for c in INSTANT:
            src = latest_bs["values"].get(c) if latest_bs else None
            if src is None and fallback and fallback["end"] >= (latest_bs or fallback)["end"]:
                src = fallback["values"].get(c)
            if src is not None:
                vals[c] = dict(src)
                method[c] = "latest balance"
        return {"end": end, "values": vals, "method": method,
                "basis": "last four quarters" if len(qs) == 4 else
                         (f"latest fiscal year ({fallback['label']})" if fallback else "partial")}

    def contiguous(qs):
        return len(qs) == 4 and all(_days(qs[i]["end"], qs[i + 1]["end"]) and
                                    80 <= _days(qs[i]["end"], qs[i + 1]["end"]) <= 105 for i in range(3))

    q_sorted = sorted(quarters, key=lambda q: q["end"])
    last4, prior4 = q_sorted[-4:], q_sorted[-8:-4]
    a_sorted = sorted(annual, key=lambda a: a["end"])
    fy_latest = a_sorted[-1] if a_sorted else None
    fy_prior = a_sorted[-2] if len(a_sorted) >= 2 else None
    if contiguous(last4) and (not fy_latest or last4[-1]["end"] >= fy_latest["end"]):
        ttm = block(last4, fy_latest)
        ttm_prior = block(prior4, fy_prior) if contiguous(prior4) else (block([], fy_prior) if fy_prior else None)
    else:
        ttm = block([], fy_latest)
        ttm_prior = block([], fy_prior) if fy_prior else None
    return ttm, ttm_prior


def build_statements(symbol: str, as_of: Optional[str] = None, n_quarters: int = 20,
                     n_years: int = 10) -> Dict[str, Any]:
    """Standardized statements for one company, as known on `as_of`."""
    loaded = load_facts(symbol, as_of)
    out = build_from_facts(symbol, loaded["facts"], as_of, n_quarters, n_years)
    out["as_of_honored"] = loaded["as_of_honored"] if as_of else True
    out["provider"] = loaded.get("provider")
    if not out.get("available") and loaded["unavailable"]:
        out["reason"] = loaded["unavailable"][0].get("reason") or out.get("reason")
    out["warnings"] = out.get("warnings", []) + [w for w in loaded["warnings"] if "pit_capable" not in w]
    return out


def value(block: Optional[Dict[str, Any]], concept: str) -> Optional[float]:
    """The number in a period block, or None."""
    if not block:
        return None
    c = (block.get("values") or {}).get(concept)
    return None if c is None else c.get("value")
