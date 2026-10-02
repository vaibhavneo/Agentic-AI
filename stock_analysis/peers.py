"""
Comparables: who the company should be measured against, and how it measures.

Peer set
  Companies SEC classifies under the same SIC industry code, sized from SEC's
  cross-company "frames" (revenue for operating companies, total assets for
  financials), nearest in size first. Size comes from the frames only to CHOOSE
  peers; every peer's figures in the table come from its own filings, built by
  the same statement engine as the company itself, as of the same date. A
  caller can name peers instead, and the response says which way they were chosen.

Comparison
  Valuation multiples, growth, margins, return on capital and the
  earnings-quality score, side by side, with the peer median and where the
  company ranks. Peers whose figures cannot be built are listed as excluded
  with the reason, not silently dropped.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .company import FINANCIAL_KINDS
from .statements import value

METRICS = [
    # key, label, lower_is_cheaper (for valuation multiples)
    ("pe", "P/E", True), ("ev_sales", "EV/Sales", True), ("ev_ebit", "EV/EBIT", True),
    ("p_fcf", "P/FCF", True), ("pb", "P/B", True), ("fcf_yield", "FCF yield", False),
    ("revenue_growth", "Revenue growth", False), ("gross_margin", "Gross margin", False),
    ("operating_margin", "Operating margin", False), ("roic", "Return on invested capital", False),
    ("return_on_equity", "Return on equity", False), ("quality_score", "Earnings-quality score", False),
]
VALUATION = ("pe", "ev_sales", "ev_ebit", "p_fcf", "pb")


def _size_period(as_of: Optional[str]) -> int:
    from datetime import date
    d = date.fromisoformat(as_of[:10]) if as_of else date.today()
    # A calendar year's frame fills in as 10-Ks arrive by the end of March.
    return d.year - 1 if d.month >= 5 else d.year - 2


def candidate_sizes(symbol: str, sic: str, financial: bool, as_of: Optional[str]) -> Dict[str, Any]:
    from financial_data import gateway as gw
    members = gw.get("filings", symbol, concepts=["industry_members"], sic=sic)["data"]
    year = _size_period(as_of)
    if financial:
        tags = [("Assets", f"CY{year}Q4I")]
    else:
        tags = [("Revenues", f"CY{year}"), ("RevenueFromContractWithCustomerExcludingAssessedTax", f"CY{year}")]
    sizes: Dict[int, float] = {}
    for tag, period in tags:
        res = gw.get("filings", symbol, concepts=["frame"], tag=tag, period=period)
        for cik, v in (res["data"][0]["extra"]["values"] if res["data"] else {}).items():
            if v and v > 0:
                sizes[int(cik)] = max(sizes.get(int(cik), 0.0), float(v))
    out = []
    for d in members:
        ex = d.get("extra") or {}
        if ex.get("ticker") and ex.get("cik") in sizes:
            out.append({"ticker": ex["ticker"], "cik": ex["cik"], "size": sizes[ex["cik"]]})
    return {"candidates": out, "size_basis": f"{'total assets' if financial else 'revenue'} "
                                              f"(SEC frames, calendar {year})", "industry_members": len(members)}


def company_row(symbol: str, kind: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """One company's line in the comparison, from its own filings."""
    from .market import market_inputs
    from .quality import assess, returns_and_growth
    from .statements import build_statements
    from .valuation import multiples
    try:
        st = build_statements(symbol, as_of=as_of)
    except Exception as e:
        return {"ticker": symbol, "ok": False, "reason": f"statements failed: {type(e).__name__}"}
    if not st.get("available"):
        return {"ticker": symbol, "ok": False, "reason": st.get("reason") or "no statements"}
    if (st.get("filer") or {}).get("is_foreign"):
        return {"ticker": symbol, "ok": False, "reason": "foreign filer — not used as a peer (annual-only, "
                                                          "different currency)"}
    mkt = market_inputs(symbol, st, as_of)
    if not mkt.get("available"):
        return {"ticker": symbol, "ok": False, "reason": mkt.get("reason") or "no market data"}
    mult = multiples(st, mkt, kind)
    ctx = returns_and_growth(st)
    q = assess(st, kind)
    row = {"ticker": symbol.upper(), "ok": True, "market_cap_usd": mkt["market_cap_usd"],
           "revenue_ttm": value(st.get("ttm"), "revenue"), "period_end": (st.get("ttm") or {}).get("end"),
           "quality_score": q.get("score"), "quality_grade": q.get("grade"),
           "revenue_growth": ctx.get("revenue_growth"), "gross_margin": ctx.get("gross_margin"),
           "operating_margin": ctx.get("operating_margin"), "roic": ctx.get("roic"),
           "return_on_equity": ctx.get("return_on_equity")}
    for k in ("pe", "ev_sales", "ev_ebit", "p_fcf", "pb", "fcf_yield"):
        row[k] = mult.get(k)
    return row


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def compare(target: Dict[str, Any], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Peer medians, the company's rank, and premium/discount on valuation. Pure."""
    ok = [p for p in peers if p.get("ok")]
    stats = {}
    for key, label, cheaper_low in METRICS:
        vals = [p.get(key) for p in ok if p.get(key) is not None]
        med = _median(vals)
        t = target.get(key)
        rank = None
        if t is not None and vals:
            rank = sum(1 for v in vals if v < t) / len(vals)
        prem = (t / med - 1) if (key in VALUATION and t is not None and med and med > 0 and t > 0) else None
        stats[key] = {"label": label, "company": t, "peer_median": med, "n_peers": len(vals),
                      "percentile_vs_peers": None if rank is None else round(rank, 2),
                      "premium_to_median": None if prem is None else round(prem, 4)}
    prems = [stats[k]["premium_to_median"] for k in VALUATION if stats[k]["premium_to_median"] is not None]
    quality_rank = stats["quality_score"]["percentile_vs_peers"]
    growth_rank = stats["revenue_growth"]["percentile_vs_peers"]
    reading = None
    if prems:
        avg = sum(prems) / len(prems)
        reading = (f"Valued at a {abs(100 * avg):.0f}% {'premium to' if avg > 0 else 'discount to'} the peer median "
                   f"on average across {len(prems)} multiple(s)")
        if growth_rank is not None:
            reading += f"; revenue growth ranks above {100 * growth_rank:.0f}% of peers"
        if quality_rank is not None:
            reading += f"; earnings quality above {100 * quality_rank:.0f}% of peers"
        reading += "."
    return {"stats": stats, "average_valuation_premium": None if not prems else round(sum(prems) / len(prems), 4),
            "reading": reading}


def build_peers(symbol: str, profile: Dict[str, Any], statements: Dict[str, Any], market: Dict[str, Any],
                as_of: Optional[str] = None, n: int = 8, override: Optional[List[str]] = None) -> Dict[str, Any]:
    kind = profile.get("industry_kind", "unknown")
    financial = kind in FINANCIAL_KINDS
    out: Dict[str, Any] = {"available": False, "symbol": symbol.upper(), "as_of": as_of}
    if override:
        tickers = [t.upper() for t in override if t.upper() != symbol.upper()][:15]
        out["selection"] = {"method": "named by the caller", "tickers": tickers}
    else:
        sic = profile.get("sic")
        if not sic:
            out["reason"] = "no SIC industry code on record"
            return out
        cands = candidate_sizes(symbol, sic, financial, as_of)
        t = statements.get("ttm") or {}
        fx = (market.get("fx") or {}).get("rate", 1.0) if market.get("available") else 1.0
        own = value(t, "assets" if financial else "revenue")
        if not own:
            out["reason"] = "the company's own size (revenue/assets) is not reported"
            return out
        own_usd = own * fx
        pool = [c for c in cands["candidates"] if c["ticker"] != symbol.upper()
                and c["cik"] != profile.get("cik")]
        pool.sort(key=lambda c: abs(math.log(c["size"]) - math.log(own_usd)))
        # Within a tenth to ten times the company's size where there are enough
        # such peers: the largest company in a code otherwise gets micro-caps as
        # its "nearest" (Coca-Cola was matched to small wineries).
        banded = [c for c in pool if 0.1 <= c["size"] / own_usd <= 10]
        chosen = banded if len(banded) >= 4 else pool
        tickers = [c["ticker"] for c in chosen[: n * 2]]
        out["selection"] = {"method": f"same SIC code {sic} ({profile.get('sic_description')}), nearest in "
                                      f"{cands['size_basis']}"
                                      + ("" if len(banded) >= 4 else
                                         " — fewer than four within 10x its size, so the nearest at any size"),
                            "industry_members": cands["industry_members"], "sized_candidates": len(pool),
                            "company_size_usd": own_usd}
    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(lambda tk: company_row(tk, kind, as_of), tickers))
    good = [r for r in rows if r.get("ok")][:n]
    out["excluded"] = [{"ticker": r["ticker"], "reason": r["reason"]} for r in rows if not r.get("ok")]
    out["peers"] = good
    if not good:
        out["reason"] = "no peer could be measured from its filings"
        return out
    from .quality import assess, returns_and_growth
    from .valuation import multiples
    mult = multiples(statements, market, kind) if market.get("available") else {}
    ctx = returns_and_growth(statements)
    q = assess(statements, kind)
    target = {"ticker": symbol.upper(), "market_cap_usd": market.get("market_cap_usd"),
              "quality_score": q.get("score"), **{k: mult.get(k) for k in ("pe", "ev_sales", "ev_ebit", "p_fcf",
                                                                           "pb", "fcf_yield")},
              **{k: ctx.get(k) for k in ("revenue_growth", "gross_margin", "operating_margin", "roic",
                                         "return_on_equity")}}
    out.update({"available": True, "company": target, "comparison": compare(target, good)})
    return out
