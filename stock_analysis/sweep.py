"""
The same fundamentals read across many names at once — for the portfolio
brief's red-flag sweep, the filing watcher and the screener.

Each name gets the compact read (score, grade, filing findings), built from
the cached report (six hours), in parallel. Names that are not SEC filers
(ETFs, coins, delisted tickers) are listed as such, never dropped.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

SWEEP_SECTIONS = ["quality", "filings", "score"]


def compact(rep: Dict[str, Any]) -> Dict[str, Any]:
    if not rep.get("available"):
        return {"available": False, "reason": rep.get("reason")}
    q, f, s = rep.get("quality") or {}, rep.get("filings") or {}, rep.get("score") or {}
    flags = f.get("flags") or []
    return {
        "available": True,
        "score": s.get("score"),
        "quality_grade": q.get("grade"),
        "quality_score": q.get("score"),
        "concerns": [x.get("title") for x in flags if x.get("severity") == "CONCERN"],
        "watch": [x.get("title") for x in flags if x.get("severity") == "WATCH"],
        "quality_concerns": [t.get("test") for t in q.get("flags", []) if t.get("status") == "CONCERN"],
        "summary": (rep.get("summary") or [])[:3],
        "data_lag": rep.get("data_lag"),
        "industry_kind": (rep.get("profile") or {}).get("industry_kind"),
        "name": (rep.get("profile") or {}).get("name"),
    }


def sweep(tickers: List[str], as_of: Optional[str] = None, sections: Optional[List[str]] = None,
          workers: int = 4) -> Dict[str, Dict[str, Any]]:
    from .report import build_report
    syms = list(dict.fromkeys(t.upper().strip() for t in tickers if t and t.strip()))

    def one(t):
        try:
            return t, compact(build_report(t, as_of=as_of, include=sections or SWEEP_SECTIONS))
        except Exception as e:
            return t, {"available": False, "reason": f"{type(e).__name__}: {e}"}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, syms))


def red_flags(reads: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The names a reader should look at first: filing concerns, then a D/F grade."""
    out = []
    for t, r in reads.items():
        if not r.get("available"):
            continue
        if r["concerns"] or r.get("quality_grade") in ("D", "F"):
            out.append({"ticker": t, "concerns": r["concerns"], "quality_grade": r.get("quality_grade"),
                        "quality_concerns": r["quality_concerns"], "score": r.get("score")})
    out.sort(key=lambda x: (-len(x["concerns"]), x.get("score") if x.get("score") is not None else 999))
    return out
