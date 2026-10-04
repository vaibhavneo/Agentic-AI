"""
Daily evaluation history — so "is it getting better?" has an answer.

One row per (run date, horizon, metric), overwritten within a day and never
across days. Canonical ledger only: a secondary deployment's scorecard reads
quarantined rows and would record a history of nothing.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_history (
    run_date     TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    metric       TEXT NOT NULL,
    value        REAL,
    n            INTEGER,
    independent_windows INTEGER,
    PRIMARY KEY (run_date, horizon_days, metric)
);
"""

METRICS = {
    "rank_ic": lambda c: (c["ranking"]["rank_ic"]["mean"], c["ranking"]["rank_ic"]["n_dates"]),
    "rank_ic_t": lambda c: (c["ranking"]["rank_ic"]["t"], c["ranking"]["rank_ic"]["n_dates"]),
    "bull_minus_bear_excess_pct": lambda c: (c["ranking"]["bull_minus_bear_excess_pct"]["mean"],
                                             c["ranking"]["bull_minus_bear_excess_pct"]["n_dates"]),
    "hit_on_price": lambda c: (c["direction"]["hit_on_price"]["mean"], c["direction"]["directional_calls"]),
    "hit_vs_spy": lambda c: (c["direction"]["hit_vs_spy"]["mean"], c["direction"]["directional_calls"]),
    "p_up_brier": lambda c: (c["p_up"].get("brier"), c["p_up"].get("n")),
    "p_up_skill_vs_trailing": lambda c: (c["p_up"].get("skill_vs_trailing_base_rate"), c["p_up"].get("n")),
    "p_up_ece": lambda c: (c["p_up"].get("ece"), c["p_up"].get("n")),
    "p_beat_brier": lambda c: (c["p_beat_spy"].get("brier"), c["p_beat_spy"].get("n")),
}


def _conn() -> sqlite3.Connection:
    from data import prediction_ledger as pl
    conn = sqlite3.connect(pl._db(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def record(report: Dict[str, Any], run_date: Optional[str] = None) -> Dict[str, Any]:
    from data import prediction_ledger as pl
    if not pl.is_canonical_ledger():
        return {"recorded": 0, "skipped": f"ledger role {pl.ledger_role()} is not evidence"}
    day = run_date or datetime.now().strftime("%Y-%m-%d")
    rows = []
    for h, card in (report.get("horizons") or {}).items():
        w = card["coverage"]["independent_windows"]
        for name, fn in METRICS.items():
            try:
                value, n = fn(card)
            except (KeyError, TypeError):
                continue
            rows.append((day, int(h), name, value, n, w))
    conn = _conn()
    try:
        conn.executemany("INSERT OR REPLACE INTO evaluation_history VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    return {"recorded": len(rows), "run_date": day}


def series(metric: str, horizon: int, limit: int = 365) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT run_date, value, n, independent_windows FROM evaluation_history
                WHERE metric=? AND horizon_days=? ORDER BY run_date DESC LIMIT ?""",
            (metric, int(horizon), int(limit))).fetchall()][::-1]
    finally:
        conn.close()
