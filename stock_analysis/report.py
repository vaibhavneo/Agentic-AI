"""
The full Stock Analysis report — what the agent, the API and the tab serve.

Sections run in order and each can fail on its own without sinking the rest
(a company with no price still has statements; one whose 20-F layout defeats
the section reader still has its numbers). Every section carries its own
`available` and, when false, its reason.

The summary at the top is assembled from the computed fields by fixed
sentences — no LLM writes it, so it can never state a number the report does
not contain.

Reports are cached in memory for six hours per (symbol, as_of, options): a
filing does not change within the day, and the peer table is the slow part.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

_CACHE: Dict[tuple, tuple] = {}
_TTL = 6 * 3600

SECTIONS = ("statements", "quality", "filings", "valuation", "peers", "technicals", "score")


def _trim_statements(st: Dict[str, Any]) -> Dict[str, Any]:
    """The statements as served: 8 quarters, 6 years, trailing blocks."""
    if not st.get("available"):
        return st
    keep = dict(st)
    keep["quarters"] = st.get("quarters", [])[:8]
    keep["annual"] = st.get("annual", [])[:6]
    keep["restatements"] = [r for r in st.get("restatements", []) if r["kind"] == "REVISED"][:20]
    keep["split_adjustments"] = sum(1 for r in st.get("restatements", []) if r["kind"] == "SPLIT_ADJUSTMENT")
    return keep


def data_lag(st: Dict[str, Any], filings: Dict[str, Any]) -> Optional[str]:
    """When SEC's XBRL dataset lags the filings themselves, say so (TSMC's
    April 2026 20-F is filed but not yet in the dataset)."""
    la = (filings or {}).get("latest_annual") or {}
    xb = (st or {}).get("latest_annual_report") or {}
    if la.get("filed") and xb.get("filed") and la["filed"] > xb["filed"] and la.get("accession") != xb.get("accession"):
        from .statements import _days
        if (_days(xb["filed"], la["filed"]) or 0) > 30:
            return (f"The {la.get('form')} filed {la['filed']} is not yet in SEC's structured (XBRL) data; "
                    f"the figures here are from the {xb.get('form')} filed {xb['filed']}.")
    return None


def _pct(x: Optional[float], digits: int = 1) -> str:
    return "—" if x is None else f"{100 * x:.{digits}f}%"


def summarize(rep: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    q = rep.get("quality") or {}
    if q.get("available"):
        if q.get("grade"):
            concerns = [f["test"] for f in q.get("flags", []) if f["status"] == "CONCERN"]
            lines.append(f"Earnings quality: grade {q['grade']} ({q['score']:.0f}/100)"
                         + (f" — concerns: {', '.join(concerns[:3])}" if concerns else " — no test at concern level")
                         + ".")
        else:
            lines.append(f"Earnings quality: not graded — {q.get('not_graded_reason')}.")
    f = rep.get("filings") or {}
    if f.get("available"):
        s = f.get("summary") or {}
        top = [x["title"] for x in f.get("flags", []) if x["severity"] == "CONCERN"][:2]
        if s.get("concerns") or s.get("watch"):
            lines.append(f"Filings: {s.get('concerns', 0)} concern(s), {s.get('watch', 0)} to watch"
                         + (f" — {'; '.join(top)}" if top else "") + ".")
        else:
            lines.append("Filings: no red flags in the last three years of filings.")
    ctx = (q.get("context") or {}) if q.get("available") else {}
    if ctx:
        parts = []
        if ctx.get("revenue_growth") is not None:
            parts.append(f"revenue {'+' if ctx['revenue_growth'] >= 0 else ''}{_pct(ctx['revenue_growth'])} "
                         "over the trailing year")
        if ctx.get("operating_margin") is not None:
            parts.append(f"{_pct(ctx['operating_margin'], 0)} operating margin")
        if ctx.get("roic") is not None:
            parts.append(f"{_pct(ctx['roic'], 0)} return on invested capital")
        if parts:
            lines.append("Business: " + ", ".join(parts) + ".")
    v = rep.get("valuation") or {}
    m = v.get("multiples") or {}
    if m.get("available"):
        bits = []
        if m.get("pe"):
            bits.append(f"{m['pe']:.1f}× trailing earnings")
        if m.get("fcf_yield") is not None:
            bits.append(f"{_pct(m['fcf_yield'])} free-cash-flow yield")
        elif m.get("pb"):
            bits.append(f"{m['pb']:.2f}× book value")
        ig = v.get("implied_growth") or {}
        line = "Valuation: " + ", ".join(bits) if bits else "Valuation:"
        if ig.get("reading"):
            line += ". " + ig["reading"]
        if m.get("stale_warning"):
            line += f" (Caution: {m['stale_warning']}.)"
        lines.append(line if line.endswith(".") or line.endswith(")") else line + ".")
    elif v:
        lines.append(f"Valuation: not computed — {(m or {}).get('reason') or v.get('reason')}.")
    p = rep.get("peers") or {}
    if p.get("available") and (p.get("comparison") or {}).get("reading"):
        method = (p.get("selection") or {}).get("method") or ""
        caveat = (" Caution: no company in its industry code is within 10× its size, so these peers are "
                  "much smaller." if "fewer than four within 10x" in method else "")
        lines.append("Peers (" + ", ".join(r["ticker"] for r in p.get("peers", [])[:6]) + "): "
                     + p["comparison"]["reading"] + caveat)
    t = rep.get("technicals") or {}
    if t.get("available"):
        r12 = (t.get("returns") or {}).get("12m")
        rel = (t.get("vs_market") or {}).get("12m")
        lines.append(f"Price: {t.get('trend')}"
                     + (f", {'+' if r12 >= 0 else ''}{_pct(r12, 0)} over 12 months" if r12 is not None else "")
                     + (f" ({'+' if rel >= 0 else ''}{_pct(rel, 0)} vs the market)" if rel is not None else "")
                     + ". Descriptive only.")
    sc = rep.get("score") or {}
    if sc.get("available"):
        lines.append(f"Fundamentals score: {sc['score']:.0f}/100 ({sc['version']})"
                     + (f", after a {sc['penalty']:.0f}-point filing penalty" if sc.get("penalty") else "") + ".")
    if rep.get("data_lag"):
        lines.append(rep["data_lag"])
    return lines


def build_report(symbol: str, as_of: Optional[str] = None, include: Optional[List[str]] = None,
                 peers_override: Optional[List[str]] = None, mdna_summary: bool = False,
                 progress: Optional[Callable[[str, str], None]] = None, use_cache: bool = True) -> Dict[str, Any]:
    from .company import profile as get_profile
    from .filings import review, _annual_text
    from .market import market_inputs
    from .peers import build_peers
    from .quality import assess
    from .scoring import score_components
    from .statements import build_statements
    from .technicals import build_technicals
    from .valuation import multiples, history, implied_growth

    symbol = symbol.upper().strip()
    want = set(include or SECTIONS)
    key = (symbol, as_of, tuple(sorted(want)), tuple(peers_override or ()), mdna_summary)
    if use_cache and key in _CACHE and time.time() - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    say = progress or (lambda stage, msg: None)
    t0 = time.time()
    rep: Dict[str, Any] = {"symbol": symbol, "as_of": as_of, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "available": False, "timings": {}}

    def timed(name, fn):
        t = time.time()
        try:
            return fn()
        except Exception as e:
            return {"available": False, "reason": f"{type(e).__name__}: {e}"}
        finally:
            rep["timings"][name] = round(time.time() - t, 2)

    say("profile", "Looking up the SEC registrant")
    prof = timed("profile", lambda: get_profile(symbol))
    rep["profile"] = prof
    if not prof.get("available"):
        rep["reason"] = prof.get("reason") or "not an SEC registrant"
        return rep
    kind = prof.get("industry_kind", "unknown")

    say("statements", "Building statements from 10-K/10-Q/20-F filings")
    st = timed("statements", lambda: build_statements(symbol, as_of=as_of))
    if not st.get("available"):
        reason = st.get("reason") or "no financial statements"
        if "HTTP 404" in reason or "no_matching_xbrl" in reason:
            reason = (f"SEC holds no financial-statement data for {prof.get('name') or symbol} — funds, trusts "
                      "and some registrants file no 10-K, 10-Q or 20-F")
        rep["reason"] = reason
        rep["statements"] = {"available": False, "reason": reason}
        return rep
    rep["available"] = True

    say("quality", "Testing quality of earnings")
    q = timed("quality", lambda: assess(st, kind))
    rep["quality"] = q

    fil: Dict[str, Any] = {}
    if want & {"filings", "score", "valuation", "peers"}:
        say("filings", "Reading the filings")
        fil = timed("filings", lambda: review(symbol, as_of, mdna_summary=mdna_summary))
        rep["filings"] = fil if "filings" in want else {"available": fil.get("available"),
                                                        "summary": fil.get("summary")}
    rep["data_lag"] = data_lag(st, fil)

    mkt: Dict[str, Any] = {"available": False}
    if want & {"valuation", "peers", "score"}:
        say("valuation", "Pricing the company")
        text = None
        if (st.get("filer") or {}).get("is_foreign") and fil.get("latest_annual"):
            text = timed("annual_text", lambda: _annual_text(symbol, fil["latest_annual"]))
            text = text if isinstance(text, str) else None
        mkt = timed("market", lambda: market_inputs(symbol, st, as_of, annual_text=text))
        mult = multiples(st, mkt, kind)
        hist = timed("history", lambda: history(st, symbol, kind, as_of, ads_ratio=mkt.get("ads_ratio") or 1.0,
                                                fx_rate=(mkt.get("fx") or {}).get("rate", 1.0))) \
            if mkt.get("available") else {"available": False, "reason": mkt.get("reason")}
        rep["valuation"] = {"market": {k: mkt.get(k) for k in ("available", "reason", "price", "price_date",
                                                                "shares", "shares_source", "ads_ratio",
                                                                "ads_ratio_source", "currency", "fx",
                                                                "market_cap_usd", "enterprise_value_usd",
                                                                "warnings")},
                            "multiples": mult, "history": hist, "implied_growth": implied_growth(st, mkt, kind)}

    if "peers" in want:
        say("peers", "Building the peer comparison")
        rep["peers"] = timed("peers", lambda: build_peers(symbol, prof, st, mkt, as_of,
                                                          override=peers_override))
    if "technicals" in want:
        say("technicals", "Price context around the filing calendar")
        rep["technicals"] = timed("technicals", lambda: build_technicals(symbol, prof, (fil or {}).get(
            "recent_filings_all") or _all_filings(symbol, as_of), as_of))
    if "score" in want:
        sc = score_components(st, q, kind, mkt, (fil or {}).get("flags") or [])
        sc["available"] = sc["score"] is not None
        rep["score"] = sc

    rep["statements"] = _trim_statements(st) if "statements" in want else {
        "available": True, "filer": st.get("filer"), "ttm": st.get("ttm")}
    rep["summary"] = summarize(rep)
    rep["timings"]["total"] = round(time.time() - t0, 2)
    say("done", "Report ready")
    if use_cache:
        _CACHE[key] = (time.time(), rep)
    return rep


def _all_filings(symbol: str, as_of: Optional[str]) -> List[Dict[str, Any]]:
    from .filings import filing_index
    try:
        return filing_index(symbol, as_of)["filings"]
    except Exception:
        return []
