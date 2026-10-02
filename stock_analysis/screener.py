"""
Screener — the fundamentals read across a universe, filterable.

The desk declined to pick names because it had no ranked universe behind the
question. This gives it one, with its basis stated: every name in the
universe is scored by the same report the Stock Analysis tab shows (filings,
earnings quality, valuation, v2 score), refreshed by the maintenance
scheduler and cached in the state store, so a screen answers in milliseconds.

A screen is a FILTER, not a recommendation. The v2 score's return edge over
the old pillar was not statistically significant in the 2026-10-02
evaluation (docs/FUNDAMENTALS_V2_EVALUATION.md); the response says so.

Universe: watchlist.txt (liquid large caps across sectors) plus watched names.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

CAVEAT = ("A filter over computed fundamentals, not a recommendation. The fundamentals score's edge over the "
          "previous pillar was not statistically significant in the 2026-10-02 evaluation.")


def _row(t: str) -> Dict[str, Any]:
    from .report import build_report
    try:
        rep = build_report(t, include=["quality", "filings", "valuation", "score"])
    except Exception as e:
        return {"ticker": t, "available": False, "reason": f"{type(e).__name__}"}
    if not rep.get("available"):
        return {"ticker": t, "available": False, "reason": rep.get("reason")}
    q, f, s = rep.get("quality") or {}, rep.get("filings") or {}, rep.get("score") or {}
    v = rep.get("valuation") or {}
    m, ig = v.get("multiples") or {}, v.get("implied_growth") or {}
    ctx = q.get("context") or {}
    flags = f.get("flags") or []
    return {
        "ticker": t, "available": True, "name": (rep.get("profile") or {}).get("name"),
        "industry": (rep.get("profile") or {}).get("sic_description"),
        "industry_kind": (rep.get("profile") or {}).get("industry_kind"),
        "score": s.get("score"), "quality_grade": q.get("grade"), "quality_score": q.get("score"),
        "filing_concerns": sum(1 for x in flags if x.get("severity") == "CONCERN"),
        "filing_watch": sum(1 for x in flags if x.get("severity") == "WATCH"),
        "concern_titles": [x.get("title") for x in flags if x.get("severity") == "CONCERN"][:3],
        "market_cap_usd": m.get("market_cap_usd"), "pe": m.get("pe"), "ev_sales": m.get("ev_sales"),
        "p_fcf": m.get("p_fcf"), "fcf_yield": m.get("fcf_yield"),
        "implied_fcf_growth": ig.get("implied_fcf_growth"), "delivered_fcf_growth": ig.get("delivered_fcf_growth"),
        "revenue_growth": ctx.get("revenue_growth"), "operating_margin": ctx.get("operating_margin"),
        "roic": ctx.get("roic"), "stale": bool(m.get("stale_warning") or rep.get("data_lag")),
    }


def refresh(universe: Optional[List[str]] = None, workers: int = 4) -> Dict[str, Any]:
    from .watcher import watched, _conn
    names = universe or watched()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(_row, names))
    snap = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": len(rows),
            "n_available": sum(1 for r in rows if r.get("available")), "seconds": round(time.time() - t0, 1),
            "rows": rows}
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS screener (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT)")
        c.execute("INSERT OR REPLACE INTO screener VALUES (1, ?)", (json.dumps(snap, default=str),))
    return {k: v for k, v in snap.items() if k != "rows"}


def latest() -> Optional[Dict[str, Any]]:
    from .watcher import _conn
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS screener (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT)")
        r = c.execute("SELECT payload FROM screener WHERE id = 1").fetchone()
    return json.loads(r["payload"]) if r else None


def screen(rows: List[Dict[str, Any]], min_score: Optional[float] = None, grades: Optional[List[str]] = None,
           max_pe: Optional[float] = None, min_fcf_yield: Optional[float] = None,
           no_filing_concerns: bool = False, min_revenue_growth: Optional[float] = None,
           sort: str = "score", descending: bool = True, limit: int = 100) -> List[Dict[str, Any]]:
    """Pure filter + sort over screener rows."""
    out = []
    for r in rows:
        if not r.get("available"):
            continue
        if min_score is not None and (r.get("score") is None or r["score"] < min_score):
            continue
        if grades and r.get("quality_grade") not in grades:
            continue
        if max_pe is not None and (r.get("pe") is None or r["pe"] > max_pe):
            continue
        if min_fcf_yield is not None and (r.get("fcf_yield") is None or r["fcf_yield"] < min_fcf_yield):
            continue
        if no_filing_concerns and r.get("filing_concerns"):
            continue
        if min_revenue_growth is not None and (r.get("revenue_growth") is None
                                               or r["revenue_growth"] < min_revenue_growth):
            continue
        out.append(r)
    out.sort(key=lambda r: (r.get(sort) is None, (-(r.get(sort) or 0) if descending else (r.get(sort) or 0))))
    return out[:limit]
