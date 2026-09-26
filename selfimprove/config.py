"""
The ACTIVE values of the tunable surface, and the only path that changes them.

Defaults come from the code that owns each knob (backtest.pillars.CORE_WEIGHTS
for the weights), so an untouched system behaves exactly as it did before this
package existed and deleting every row here restores it. That property is the
rollback story: there is no migration to undo.

Overrides are stored per (group, horizon). Horizon scoping is the whole reason
the store exists rather than a module constant — the measured relationship
between the pillars and forward return differs by horizon, and one global
CORE_WEIGHTS cannot express that.

Writes go through `apply()`, which re-checks the surface. The gate in verify.py
already checked it, but a knob can also be set by an operator through the API,
and a bound that is only enforced on one path is not a bound.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from . import surface as S

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tunable_config (
    grp           TEXT NOT NULL,
    horizon_days  INTEGER NOT NULL,
    key           TEXT NOT NULL,
    value         REAL NOT NULL,
    updated_at    TEXT NOT NULL,
    proposal_id   TEXT,
    PRIMARY KEY (grp, horizon_days, key)
);
CREATE TABLE IF NOT EXISTS tunable_config_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at    TEXT NOT NULL,
    epoch         REAL NOT NULL,
    grp           TEXT NOT NULL,
    horizon_days  INTEGER NOT NULL,
    key           TEXT NOT NULL,
    old_value     REAL,
    new_value     REAL NOT NULL,
    proposal_id   TEXT
);
CREATE TRIGGER IF NOT EXISTS tunable_history_no_update
BEFORE UPDATE ON tunable_config_history
BEGIN SELECT RAISE(ABORT, 'config history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS tunable_history_no_delete
BEFORE DELETE ON tunable_config_history
BEGIN SELECT RAISE(ABORT, 'config history is append-only'); END;
"""

# Horizon 0 means "applies to every horizon" — the shape a global default
# takes in a per-horizon store.
ALL_HORIZONS = 0

# The loop tunes at the ledger's evaluation horizons. The DESK, however, decides
# at 45, 91 or 126 days depending on the volatility regime — so an exact-match
# lookup found nothing for almost every real decision, and the learned
# parameters were served by this module and consulted by nothing. That is the
# third time this pattern has appeared in this package's own wiring.
#
# So a requested horizon resolves to the nearest TUNED horizon, within a
# proportional tolerance. Proportional rather than absolute because 20 days
# away means something very different at a 5-day horizon than at a 252-day one.
TUNED_HORIZONS = (5, 20, 60, 126, 252, 504)

# Beyond this relative distance the nearest tuned horizon is not a reasonable
# stand-in and no override applies. 0.5 lets 91 resolve to 60 (34% away) and
# 45 resolve to 60 (33%), while a 5-day request will not borrow 20-day weights.
HORIZON_TOLERANCE = 0.5


def resolve_horizon(horizon: Optional[int]) -> Tuple[Optional[int], str]:
    """Map a requested horizon onto the nearest horizon the loop tunes.

    Returns (resolved_horizon, note). A resolved horizon that differs from the
    request is disclosed in the note and ends up in the score's
    `weight_source`, because a reader comparing two decisions needs to know
    that one was scored with parameters learned at a different horizon.
    """
    if horizon is None:
        return None, "no horizon was named, so no learned parameters apply"
    h = int(horizon)
    if h in TUNED_HORIZONS:
        return h, f"{h}d is tuned directly"
    nearest = min(TUNED_HORIZONS, key=lambda t: abs(t - h))
    rel = abs(nearest - h) / float(max(h, 1))
    if rel > HORIZON_TOLERANCE:
        return None, (f"{h}d has no tuned horizon within "
                      f"{HORIZON_TOLERANCE:.0%} (nearest is {nearest}d, "
                      f"{rel:.0%} away), so the shipped defaults apply")
    return nearest, (f"{h}d resolved to the {nearest}d tuned horizon "
                     f"({rel:.0%} away)")

_ready: set = set()


def _conn() -> sqlite3.Connection:
    from data import prediction_ledger as PL
    path = PL._db()
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    if path not in _ready:
        conn.executescript(_SCHEMA)
        conn.commit()
        _ready.add(path)
    return conn


def defaults(group: str) -> Dict[str, float]:
    """What the knob is when nothing has overridden it, read from the module
    that owns it rather than duplicated here."""
    if group == S.PILLAR_WEIGHTS:
        from backtest.pillars import CORE_WEIGHTS
        return dict(CORE_WEIGHTS)
    if group == S.CONFIDENCE_MAP:
        # The incumbent mapping the ledger measured against: these are the
        # numbers confidence_reliability compares realised win rates to.
        return {"LOW": 0.717, "MEDIUM": 0.877, "HIGH": 0.95}
    return {}


def active(group: str, horizon: Optional[int] = None) -> Dict[str, float]:
    """Effective values, most specific winning:

        shipped defaults  <  committed seed  <  ALL_HORIZONS  <  this horizon

    The seed layer carries parameters learned on the canonical ledger to
    deployments that cannot learn (their snapshots are quarantined, so their
    evidence population is empty). See selfimprove/seed.py. A deployment that
    learned its own value always overrides the seed, so exporting a seed and
    then reading it back is not circular.
    """
    out = defaults(group)
    resolved, _note = resolve_horizon(horizon)
    if resolved is not None:
        try:
            from .seed import for_group as _seeded
            out.update(_seeded(group, resolved))
        except Exception:
            pass        # a bad seed costs the learned values, never the score
    horizon = resolved
    try:
        conn = _conn()
        rows = conn.execute(
            "SELECT horizon_days, key, value FROM tunable_config "
            "WHERE grp = ? AND horizon_days IN (?, ?) "
            "ORDER BY horizon_days ASC",
            (group, ALL_HORIZONS,
             int(horizon) if horizon is not None else ALL_HORIZONS)).fetchall()
        conn.close()
    except sqlite3.Error:
        return out
    for r in rows:
        out[r["key"]] = float(r["value"])
    return out


def apply(group: str, horizon: int, values: Dict[str, float],
          proposal_id: Optional[str] = None) -> Dict[str, Any]:
    """Set a whole group at one horizon. Re-validates the surface first.

    Whole-group writes only. A per-key write could leave pillar weights
    summing to something other than 1 between two statements, and anything
    reading in that window would score against a config that was never valid.
    """
    ok, why = S.check_invariant(group, values)
    if not ok:
        return {"applied": False, "reason": why}

    prev = active(group, horizon)
    now = time.time()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    try:
        conn = _conn()
        with conn:
            for key, val in values.items():
                conn.execute(
                    """INSERT INTO tunable_config
                       (grp, horizon_days, key, value, updated_at, proposal_id)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(grp, horizon_days, key) DO UPDATE SET
                         value=excluded.value, updated_at=excluded.updated_at,
                         proposal_id=excluded.proposal_id""",
                    (group, int(horizon), key, float(val), stamp, proposal_id))
                conn.execute(
                    """INSERT INTO tunable_config_history
                       (changed_at, epoch, grp, horizon_days, key,
                        old_value, new_value, proposal_id)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (stamp, now, group, int(horizon), key,
                     prev.get(key), float(val), proposal_id))
        conn.close()
    except sqlite3.Error as e:
        return {"applied": False, "reason": f"write failed: {e}"}
    return {"applied": True, "group": group, "horizon_days": horizon,
            "previous": prev, "values": dict(values), "proposal_id": proposal_id}


def revert(group: str, horizon: int,
           proposal_id: Optional[str] = None) -> Dict[str, Any]:
    """Drop the override, returning this group at this horizon to defaults.

    The override row is deleted but its history is not: `tunable_config_history`
    is append-only, so a reverted change stays visible as something that
    happened. A rollback that erases its own cause is how a system develops a
    past nobody can reconstruct.
    """
    prev = active(group, horizon)
    base = defaults(group)
    now = time.time()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    try:
        conn = _conn()
        with conn:
            conn.execute("DELETE FROM tunable_config WHERE grp=? AND horizon_days=?",
                         (group, int(horizon)))
            for key, val in base.items():
                if abs(float(prev.get(key, val)) - float(val)) > 1e-12:
                    conn.execute(
                        """INSERT INTO tunable_config_history
                           (changed_at, epoch, grp, horizon_days, key,
                            old_value, new_value, proposal_id)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (stamp, now, group, int(horizon), key,
                         prev.get(key), float(val), proposal_id))
        conn.close()
    except sqlite3.Error as e:
        return {"reverted": False, "reason": f"write failed: {e}"}
    return {"reverted": True, "group": group, "horizon_days": horizon,
            "restored": base}


def history(group: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM tunable_config_history"
    args: List[Any] = []
    if group:
        sql += " WHERE grp = ?"
        args.append(group)
    sql += " ORDER BY epoch DESC LIMIT ?"
    args.append(int(limit))
    try:
        conn = _conn()
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        conn.close()
        return rows
    except sqlite3.Error:
        return []


def overrides() -> List[Dict[str, Any]]:
    """Every active override — what differs from stock behaviour right now."""
    try:
        conn = _conn()
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM tunable_config ORDER BY grp, horizon_days, key"
        ).fetchall()]
        conn.close()
        return rows
    except sqlite3.Error:
        return []
