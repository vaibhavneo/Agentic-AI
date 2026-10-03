"""
Analysts and insiders — what the people closest to the numbers did.

  earnings surprises   reported EPS against the consensus for recent quarters
                       (beat rate, average surprise)
  analyst trend        share of buy ratings now and three months earlier
  insider activity     OPEN-MARKET trades only (Form 4 code P = purchase,
                       S = sale) over 180 days. Grants (A), option exercises
                       (M), tax withholding (F) and gifts (G) are compensation
                       mechanics, not views, and are excluded. Three or more
                       distinct insiders buying is reported as a cluster — the
                       insider pattern with the longest academic record.
                       Selling is common and usually personal; it is reported,
                       never flagged as a concern on its own.

Source: Finnhub's free tier (FINNHUB_API_KEY). Without the key the section
says what it is waiting for. Every figure is context for the reader; none of
it enters the fundamentals score until it has been measured.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

PROVIDER = "finnhub-research"
OPEN_MARKET = {"P": "purchase", "S": "sale"}
WINDOW_DAYS = 180
RECENT_QUARTERS = 8


def _get(kind: str, symbol: str, concept: str, provider: str = PROVIDER) -> Dict[str, Any]:
    from financial_data import gateway as gw
    try:
        res = gw.get(kind, symbol, provider=provider, concepts=[concept])
        return {"data": res["data"], "unavailable": res.get("unavailable") or [], "provider": provider}
    except Exception as e:
        msg = str(e)
        for var, site in (("FINNHUB_API_KEY", "finnhub.io"), ("ALPHAVANTAGE_API_KEY", "alphavantage.co"),
                          ("FMP_API_KEY", "financialmodelingprep.com")):
            if var in msg:
                msg = f"waiting for {var} (free at {site})"
        return {"data": [], "error": msg, "provider": provider}


def _surprise_source(symbol: str) -> Dict[str, Any]:
    """The longest consensus history available: Alpha Vantage (every quarter
    on record), then FMP, then Finnhub's free four quarters."""
    tried = []
    for prov in ("alphavantage", "fmp", PROVIDER):
        r = _get("events", symbol, "earnings_surprise", prov)
        if r["data"]:
            r["tried"] = tried
            return r
        tried.append(f"{prov}: {r.get('error') or 'no data'}")
    return {"data": [], "error": "; ".join(tried), "tried": tried}


def _fiscal(x: Dict[str, Any]) -> Optional[str]:
    """Finnhub labels a fiscal quarter with a calendar date rounded UP (Nvidia's
    quarter ended 2026-07-26 is '2026-09-30' — it reads as an unreported
    quarter), so its fiscal year/quarter is what a reader is shown."""
    y, q = x.get("year"), x.get("quarter")
    return f"FY{y} Q{q}" if y and q else None


def surprises(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = sorted(({"period": d.get("period_end"), "fiscal": _fiscal(d.get("extra") or {}),
                    "reported": (d.get("extra") or {}).get("reported_date"), "actual": d["value"],
                    "estimate": (d.get("extra") or {}).get("estimate"),
                    "surprise_pct": (d.get("extra") or {}).get("surprise_pct")} for d in data),
                  key=lambda r: r["period"] or "", reverse=True)
    scored = [r for r in rows if r["estimate"] is not None]
    if not scored:
        return {"available": False, "reason": "no consensus estimates returned"}
    # Alpha Vantage returns every quarter since the 1990s; a 27-year average is
    # dominated by tiny early EPS (a 1-cent beat on 2 cents is +50%). The read
    # is the last two years.
    recent = scored[:RECENT_QUARTERS]
    beats = sum(1 for r in recent if r["actual"] > r["estimate"])
    pcts = [r["surprise_pct"] for r in recent if r["surprise_pct"] is not None]
    return {"available": True, "quarters": rows[:8], "beat_rate": round(beats / len(recent), 2), "n": len(recent),
            "n_history": len(scored), "window": f"last {len(recent)} quarters",
            "avg_surprise_pct": None if not pcts else round(sum(pcts) / len(pcts), 2)}


def recommendations(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = sorted(data, key=lambda d: d.get("period_end") or "", reverse=True)
    if not rows:
        return {"available": False, "reason": "no analyst coverage returned"}

    def share(d):
        x = d.get("extra") or {}
        total = sum(x.get(k, 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
        if not total:
            return None, 0
        return (x.get("strongBuy", 0) + x.get("buy", 0)) / total, total
    now_share, now_n = share(rows[0])
    then = rows[3] if len(rows) > 3 else None
    then_share = share(then)[0] if then else None
    return {"available": now_share is not None, "period": rows[0].get("period_end"), "analysts": now_n,
            "buy_share": None if now_share is None else round(now_share, 3),
            "buy_share_3m_ago": None if then_share is None else round(then_share, 3),
            "change_3m": None if now_share is None or then_share is None else round(now_share - then_share, 3),
            "counts": (rows[0].get("extra") or {})}


def insiders(data: List[Dict[str, Any]], as_of: Optional[str] = None) -> Dict[str, Any]:
    end = date.fromisoformat(as_of[:10]) if as_of else date.today()
    start = (end - timedelta(days=WINDOW_DAYS)).isoformat()
    trades = []
    for d in data:
        ex = d.get("extra") or {}
        code = ex.get("code")
        when = str(d.get("available_at"))[:10]
        if code not in OPEN_MARKET or not (start <= when <= end.isoformat()) or ex.get("is_derivative"):
            continue
        price = ex.get("price") or 0.0
        trades.append({"name": ex.get("name"), "type": OPEN_MARKET[code], "shares": d["value"], "price": price,
                       "value": abs(d["value"]) * float(price or 0), "filed": when})
    buys = [t for t in trades if t["type"] == "purchase"]
    sells = [t for t in trades if t["type"] == "sale"]
    buyers = sorted({t["name"] for t in buys if t["name"]})
    return {"available": True, "window_days": WINDOW_DAYS, "from": start,
            "purchases": len(buys), "purchase_value": round(sum(t["value"] for t in buys), 0),
            "sales": len(sells), "sale_value": round(sum(t["value"] for t in sells), 0),
            "distinct_buyers": len(buyers), "buyers": buyers[:8],
            "cluster_buying": len(buyers) >= 3,
            "recent": sorted(trades, key=lambda t: t["filed"], reverse=True)[:10],
            "note": "open-market trades only (Form 4 codes P/S); grants, exercises, withholding and gifts excluded"}


def build_street(symbol: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"symbol": symbol.upper(), "source": "finnhub + alpha vantage (free tiers)"}
    e = _surprise_source(symbol)
    r = _get("sentiment", symbol, "analyst_recommendation")
    i = _get("filings", symbol, "insider_transaction")
    p = _get("universe", symbol, "peers")
    errs = {x.get("error") for x in (e, r, i, p) if x.get("error")}
    if errs and not e["data"] and all(x.get("error") for x in (r, i, p)):
        return {**out, "available": False, "reason": sorted(errs)[0]}
    out["available"] = True
    out["earnings_surprises"] = (dict(surprises(e["data"]), source=e.get("provider")) if e["data"] else
                                 {"available": False, "reason": e.get("error")})
    out["analysts"] = recommendations(r["data"]) if not r.get("error") else {"available": False, "reason": r["error"]}
    out["insiders"] = insiders(i["data"], as_of) if not i.get("error") else {"available": False, "reason": i["error"]}
    out["vendor_peers"] = [d["value"] for d in p["data"]][:12] if not p.get("error") else []
    if as_of:
        out["note"] = "analyst counts and peers are the vendor's current view; insider trades are cut at as_of"
    return out
