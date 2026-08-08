from __future__ import annotations

import datetime as dt
import statistics

from app.validation import validate_date_str
from database.db import get_connection
from safety.constants import VALID_WEIGHT_KG_RANGE


class WeightValidationError(ValueError):
    pass


def record_weight(profile_id: str, weight_kg: float, log_date: str | None = None, notes: str | None = None) -> dict:
    try:
        weight_kg = float(weight_kg)
    except (TypeError, ValueError):
        raise WeightValidationError("weight_kg must be a number")
    lo, hi = VALID_WEIGHT_KG_RANGE
    if not (lo <= weight_kg <= hi):
        raise WeightValidationError(f"weight_kg must be between {lo} and {hi}, got {weight_kg}")

    if log_date is not None:
        try:
            validate_date_str("log_date", log_date)
        except ValueError as e:
            raise WeightValidationError(str(e))
    log_date = log_date or dt.date.today().isoformat()
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO weight_logs (profile_id, log_date, weight_kg, notes) VALUES (?, ?, ?, ?)",
        (profile_id, log_date, weight_kg, notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM weight_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_weight_history(profile_id: str, days: int = 90) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM weight_logs WHERE profile_id = ? AND log_date >= ? ORDER BY log_date DESC, id DESC",
        (profile_id, since),
    ).fetchall()
    return [dict(r) for r in rows]


def calculate_weight_trend(profile_id: str, days: int = 30) -> dict:
    history = get_weight_history(profile_id, days)
    if len(history) < 2:
        return {"days": days, "sample_size": len(history), "direction": "insufficient_data", "delta_kg": None}

    chronological = list(reversed(history))
    delta = round(chronological[-1]["weight_kg"] - chronological[0]["weight_kg"], 1)
    if delta > 0.5:
        direction = "rising"
    elif delta < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"days": days, "sample_size": len(history), "direction": direction, "delta_kg": delta}
