"""
Append-only record of every proposal the loop has ever made, and its fate.

Append-only enforced by triggers, for the same reason the prediction ledger
is: a self-improving system whose history of changes can be edited cannot be
audited, and "why is the system behaving differently than last month" becomes
unanswerable exactly when it matters most.

Refusals are recorded as carefully as promotions, and that is the point. A
loop that only writes down its successes looks like it improves monotonically
while quietly discarding the evidence that it mostly cannot. The refusal rate
and the reasons for it ARE the honest status of the system.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS improvement_proposals (
    proposal_id    TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    epoch          REAL NOT NULL,
    cycle_id       TEXT,
    grp            TEXT NOT NULL,
    horizon_days   INTEGER,
    current_json   TEXT NOT NULL,
    candidate_json TEXT NOT NULL,
    verdict        TEXT NOT NULL,
    reason         TEXT,
    n_rows         INTEGER,
    effective_n    INTEGER,
    effect         REAL,
    metric_current REAL,
    metric_candidate REAL,
    checks_json    TEXT,
    folds_json     TEXT,
    applied        INTEGER NOT NULL DEFAULT 0,
    rolled_back_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_proposals_grp
    ON improvement_proposals(grp, horizon_days, epoch DESC);
CREATE INDEX IF NOT EXISTS idx_proposals_cycle
    ON improvement_proposals(cycle_id);

CREATE TRIGGER IF NOT EXISTS improvement_proposals_no_delete
BEFORE DELETE ON improvement_proposals
BEGIN SELECT RAISE(ABORT, 'the improvement ledger is append-only'); END;
"""

# UPDATE is allowed on exactly two columns -- the ones that record what later
# HAPPENED to a proposal (it was applied; it was rolled back). Everything that
# describes the decision itself is frozen. A trigger enforces the distinction
# rather than a convention, because a convention is what erodes.
_UPDATE_GUARD = """
CREATE TRIGGER IF NOT EXISTS improvement_proposals_frozen_fields
BEFORE UPDATE ON improvement_proposals
FOR EACH ROW WHEN (
    OLD.proposal_id   IS NOT NEW.proposal_id
 OR OLD.created_at    IS NOT NEW.created_at
 OR OLD.grp           IS NOT NEW.grp
 OR OLD.horizon_days  IS NOT NEW.horizon_days
 OR OLD.current_json  IS NOT NEW.current_json
 OR OLD.candidate_json IS NOT NEW.candidate_json
 OR OLD.verdict       IS NOT NEW.verdict
 OR OLD.reason        IS NOT NEW.reason
 OR OLD.effect        IS NOT NEW.effect
 OR OLD.checks_json   IS NOT NEW.checks_json
)
BEGIN SELECT RAISE(ABORT,
    'a proposal record is frozen; only applied/rolled_back_at may change'); END;
"""

_ready: set = set()


def _db() -> str:
    from data import prediction_ledger as PL
    return PL._db()


def _conn() -> sqlite3.Connection:
    path = _db()
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Schema once per database per process. Running executescript on every
    # connection makes every reader a writer, which is what produced
    # "database is locked" under the concurrent maintenance claims.
    if path not in _ready:
        conn.executescript(_SCHEMA + _UPDATE_GUARD)
        conn.commit()
        _ready.add(path)
    return conn


def _fingerprint(grp: str, horizon: Optional[int], candidate: Dict[str, Any],
                 epoch: float) -> str:
    import hashlib
    payload = json.dumps({"g": grp, "h": horizon, "c": candidate,
                          "t": round(epoch, 3)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def record(evaluation: Dict[str, Any], cycle_id: Optional[str] = None,
           applied: bool = False) -> Optional[str]:
    """Write one evaluated proposal. Returns its id, or None if it could not
    be written — never raises into the loop."""
    now = time.time()
    pid = _fingerprint(evaluation.get("group", ""),
                       evaluation.get("horizon_days"),
                       evaluation.get("candidate") or {}, now)
    try:
        conn = _conn()
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO improvement_proposals
                   (proposal_id, created_at, epoch, cycle_id, grp, horizon_days,
                    current_json, candidate_json, verdict, reason, n_rows,
                    effective_n, effect, metric_current, metric_candidate,
                    checks_json, folds_json, applied)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid,
                 time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), now,
                 cycle_id, evaluation.get("group"), evaluation.get("horizon_days"),
                 json.dumps(evaluation.get("current") or {}, sort_keys=True),
                 json.dumps(evaluation.get("candidate") or {}, sort_keys=True),
                 evaluation.get("verdict"), evaluation.get("reason"),
                 evaluation.get("n_rows"), evaluation.get("effective_n"),
                 evaluation.get("effect"), evaluation.get("metric_current"),
                 evaluation.get("metric_candidate"),
                 json.dumps(evaluation.get("checks") or []),
                 json.dumps(evaluation.get("folds") or []),
                 1 if applied else 0))
        conn.close()
        return pid
    except sqlite3.Error:
        return None


def mark_applied(proposal_id: str) -> bool:
    try:
        conn = _conn()
        with conn:
            conn.execute("UPDATE improvement_proposals SET applied=1 "
                         "WHERE proposal_id=?", (proposal_id,))
        conn.close()
        return True
    except sqlite3.Error:
        return False


def mark_rolled_back(proposal_id: str) -> bool:
    try:
        conn = _conn()
        with conn:
            conn.execute(
                "UPDATE improvement_proposals SET rolled_back_at=? "
                "WHERE proposal_id=?",
                (time.strftime("%Y-%m-%dT%H:%M:%S"), proposal_id))
        conn.close()
        return True
    except sqlite3.Error:
        return False


def history(group: Optional[str] = None, horizon: Optional[int] = None,
            limit: int = 100) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM improvement_proposals"
    where, args = [], []
    if group:
        where.append("grp = ?")
        args.append(group)
    if horizon is not None:
        where.append("horizon_days = ?")
        args.append(int(horizon))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY epoch DESC LIMIT ?"
    args.append(int(limit))
    try:
        conn = _conn()
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        conn.close()
    except sqlite3.Error:
        return []
    for r in rows:
        for k in ("current_json", "candidate_json", "checks_json", "folds_json"):
            try:
                r[k.replace("_json", "")] = json.loads(r.pop(k) or "null")
            except (ValueError, TypeError):
                r.pop(k, None)
    return rows


def summary() -> Dict[str, Any]:
    """The loop's honest status: how often it proposes, how often it refuses,
    and what it refuses FOR. A high refusal rate on thin evidence is the
    system working, not failing, and this shape is what says so."""
    try:
        conn = _conn()
        total = conn.execute(
            "SELECT COUNT(*) FROM improvement_proposals").fetchone()[0]
        by_verdict = {r[0]: r[1] for r in conn.execute(
            "SELECT verdict, COUNT(*) FROM improvement_proposals "
            "GROUP BY verdict")}
        applied = conn.execute(
            "SELECT COUNT(*) FROM improvement_proposals WHERE applied=1"
        ).fetchone()[0]
        rolled = conn.execute(
            "SELECT COUNT(*) FROM improvement_proposals "
            "WHERE rolled_back_at IS NOT NULL").fetchone()[0]
        reasons = [dict(r) for r in conn.execute(
            """SELECT reason, COUNT(*) AS n FROM improvement_proposals
               WHERE verdict != 'PROMOTE' GROUP BY reason
               ORDER BY n DESC LIMIT 10""").fetchall()]
        conn.close()
    except sqlite3.Error:
        return {"available": False}
    return {"available": True, "total": total, "by_verdict": by_verdict,
            "applied": applied, "rolled_back": rolled,
            "top_refusal_reasons": reasons}


def last_promotion(group: str, horizon: int) -> Optional[Dict[str, Any]]:
    """The most recent APPLIED promotion for one group/horizon, if any.

    The loop reads this to answer "has anything actually changed since I last
    moved this knob". Without it a 6-hourly cycle re-derives the same
    conclusion from the same evidence and takes another bounded step every
    cycle, walking the weights to their bounds on the strength of one
    measurement.
    """
    try:
        conn = _conn()
        row = conn.execute(
            """SELECT * FROM improvement_proposals
                WHERE grp = ? AND horizon_days = ? AND applied = 1
                  AND rolled_back_at IS NULL AND verdict = 'PROMOTE'
             ORDER BY epoch DESC LIMIT 1""",
            (group, int(horizon))).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    return dict(row) if row else None
