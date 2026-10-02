"""
Filing watcher — what the SEC index says changed, turned into alerts.

For every watched name (watchlist.txt, names added through the API, and the
connected brokerage's holdings), new filings since the last check are read
from the SEC filing index:

  CONCERN  late-filing notice (NT 10-K/10-Q/20-F); 8-K Item 4.02 (previously
           issued financials should no longer be relied on); 1.03 (bankruptcy)
  WATCH    8-K Item 4.01 (auditor change), 3.01 (listing standard), 2.06
           (material impairment), 2.04 (accelerated obligation)
  INFO     a new 10-K/10-Q/20-F — the name is re-scored, and the alert says how
           the fundamentals score moved and whether the report shows new
           control or going-concern findings

The first check of a name records what is already on file without alerting
on it (an alert for a 2019 filing is noise), except filings from the last
three days. State lives in SQLite beside the broker tokens — the Railway
volume when BROKER_TOKEN_DIR points at it — so a redeploy does not re-alert.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
ITEM_SEVERITY = {"4.02": "CONCERN", "1.03": "CONCERN", "4.01": "WATCH", "3.01": "WATCH",
                 "2.06": "WATCH", "2.04": "WATCH"}
LATE = {"NT 10-K", "NT 10-Q", "NT 20-F"}
PERIODIC = {"10-K", "10-Q", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A"}
FRESH_DAYS = 3


def _db_path() -> Path:
    d = os.getenv("STOCK_ANALYSIS_STATE_DIR") or os.getenv("BROKER_TOKEN_DIR") or str(ROOT / "data")
    Path(d).mkdir(parents=True, exist_ok=True)
    return Path(d) / "stock_analysis_state.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_db_path()), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS seen_filings (
        ticker TEXT, accession TEXT, form TEXT, filed TEXT, seen_at TEXT,
        PRIMARY KEY (ticker, accession))""")
    c.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, created_at TEXT, filed TEXT,
        severity TEXT, code TEXT, title TEXT, detail TEXT, url TEXT, accession TEXT,
        read INTEGER DEFAULT 0, UNIQUE (ticker, accession, code))""")
    c.execute("""CREATE TABLE IF NOT EXISTS watched (ticker TEXT PRIMARY KEY, added_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS last_score (ticker TEXT PRIMARY KEY, score REAL,
        grade TEXT, concerns INTEGER, at TEXT)""")
    return c


def watchlist() -> List[str]:
    p = ROOT / "watchlist.txt"
    out: List[str] = []
    if p.exists():
        for line in p.read_text().splitlines():
            t = line.split("#", 1)[0].strip().upper()
            if t:
                out.append(t)
    return out


def watched() -> List[str]:
    names = set(watchlist())
    with _conn() as c:
        names |= {r["ticker"] for r in c.execute("SELECT ticker FROM watched")}
    try:
        from broker.providers.robinhood import get_default_holdings  # read-only
        for h in (get_default_holdings() or {}).get("positions", []) or []:
            if h.get("symbol"):
                names.add(str(h["symbol"]).upper())
    except Exception:
        pass
    return sorted(names)


def add(ticker: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO watched VALUES (?, ?)", (ticker.upper(), datetime.now().isoformat()))


def remove(ticker: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM watched WHERE ticker = ?", (ticker.upper(),))


def classify(f: Dict[str, Any]) -> List[Dict[str, str]]:
    """Alerts one filing raises on its own (from the index alone). Pure."""
    out = []
    form = f.get("form") or ""
    if form in LATE:
        out.append({"severity": "CONCERN", "code": "LATE_FILING",
                    "title": f"Late-filing notice ({form})",
                    "detail": f"The company told the SEC it could not file its {form[3:]} on time."})
    if form.startswith("8-K"):
        from .filings import EIGHT_K_ITEMS
        for item in [i.strip() for i in (f.get("items") or "").split(",") if i.strip()]:
            if item in ITEM_SEVERITY:
                out.append({"severity": ITEM_SEVERITY[item], "code": f"8K_ITEM_{item.replace('.', '_')}",
                            "title": EIGHT_K_ITEMS[item][1], "detail": f"8-K Item {item}."})
    return out


def _rescore(ticker: str) -> Optional[Dict[str, Any]]:
    """A new periodic report: rebuild the read and say what moved."""
    from .report import build_report
    from .sweep import compact
    rep = compact(build_report(ticker, include=["quality", "filings", "score"], use_cache=False))
    if not rep.get("available"):
        return None
    with _conn() as c:
        prev = c.execute("SELECT * FROM last_score WHERE ticker = ?", (ticker,)).fetchone()
        c.execute("INSERT OR REPLACE INTO last_score VALUES (?, ?, ?, ?, ?)",
                  (ticker, rep.get("score"), rep.get("quality_grade"), len(rep["concerns"]),
                   datetime.now().isoformat()))
    rep["previous"] = dict(prev) if prev else None
    return rep


def check(tickers: Optional[List[str]] = None, today: Optional[str] = None) -> Dict[str, Any]:
    from .filings import filing_index
    names = tickers or watched()
    today_d = date.fromisoformat(today) if today else date.today()
    fresh_from = (today_d - timedelta(days=FRESH_DAYS)).isoformat()
    new_alerts: List[Dict[str, Any]] = []
    checked, errors = 0, []
    for t in names:
        try:
            fl = filing_index(t, fresh=True)["filings"]
        except Exception as e:
            errors.append({"ticker": t, "error": f"{type(e).__name__}"})
            continue
        checked += 1
        with _conn() as c:
            seen = {r["accession"] for r in c.execute("SELECT accession FROM seen_filings WHERE ticker = ?", (t,))}
            first_time = not seen
            fresh = [f for f in fl if f["accession"] not in seen]
            for f in fresh:
                c.execute("INSERT OR IGNORE INTO seen_filings VALUES (?, ?, ?, ?, ?)",
                          (t, f["accession"], f["form"], f["filed"], datetime.now().isoformat()))
        alertable = [f for f in fresh if not first_time or f["filed"] >= fresh_from]
        rescored = False
        for f in alertable:
            raised = classify(f)
            if f["form"] in PERIODIC and not rescored:
                rescored = True
                r = _rescore(t)
                if r:
                    prev = r.get("previous") or {}
                    moved = (f" Fundamentals score {prev.get('score'):.0f} → {r['score']:.0f}."
                             if prev.get("score") is not None and r.get("score") is not None else
                             (f" Fundamentals score {r['score']:.0f}." if r.get("score") is not None else ""))
                    new_findings = [x for x in r["concerns"] if "control" in x.lower() or "going" in x.lower()
                                    or "weakness" in x.lower()]
                    raised.append({"severity": "CONCERN" if new_findings else "INFO", "code": "NEW_REPORT",
                                   "title": f"New {f['form']} filed",
                                   "detail": (f"Re-scored from the new report.{moved}"
                                              + (f" Findings: {'; '.join(new_findings)}." if new_findings else ""))})
            with _conn() as c:
                for a in raised:
                    cur = c.execute(
                        "INSERT OR IGNORE INTO alerts (ticker, created_at, filed, severity, code, title, detail, url, "
                        "accession) VALUES (?,?,?,?,?,?,?,?,?)",
                        (t, datetime.now().isoformat(timespec="seconds"), f["filed"], a["severity"], a["code"],
                         a["title"], a["detail"], f["url"], f["accession"]))
                    if cur.rowcount:
                        new_alerts.append({"ticker": t, **a, "filed": f["filed"], "url": f["url"]})
    return {"checked": checked, "names": len(names), "new_alerts": new_alerts, "errors": errors[:10]}


def alerts(limit: int = 100, unread_only: bool = False) -> List[Dict[str, Any]]:
    with _conn() as c:
        q = "SELECT * FROM alerts" + (" WHERE read = 0" if unread_only else "")
        q += (" ORDER BY read ASC, CASE severity WHEN 'CONCERN' THEN 0 WHEN 'WATCH' THEN 1 ELSE 2 END, "
              "filed DESC, id DESC LIMIT ?")
        return [dict(r) for r in c.execute(q, (limit,))]


def mark_read(alert_id: Optional[int] = None) -> int:
    with _conn() as c:
        if alert_id is None:
            return c.execute("UPDATE alerts SET read = 1 WHERE read = 0").rowcount
        return c.execute("UPDATE alerts SET read = 1 WHERE id = ?", (alert_id,)).rowcount
