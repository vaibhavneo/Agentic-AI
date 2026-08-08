from __future__ import annotations

import datetime as dt

from app.validation import validate_date_str
from database.db import get_connection


class WaterValidationError(ValueError):
    pass


def log_water(profile_id: str, amount_ml: int, log_date: str | None = None) -> dict:
    if amount_ml <= 0:
        raise WaterValidationError("amount_ml must be > 0")
    if log_date is not None:
        try:
            validate_date_str("log_date", log_date)
        except ValueError as e:
            raise WaterValidationError(str(e))
    log_date = log_date or dt.date.today().isoformat()
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO water_logs (profile_id, log_date, amount_ml) VALUES (?, ?, ?)",
        (profile_id, log_date, amount_ml),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM water_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_today_water(profile_id: str) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_ml), 0) AS total FROM water_logs WHERE profile_id = ? AND log_date = ?",
        (profile_id, dt.date.today().isoformat()),
    ).fetchone()
    return row["total"]
