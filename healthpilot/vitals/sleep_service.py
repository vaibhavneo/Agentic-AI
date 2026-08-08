from __future__ import annotations

import datetime as dt

from app.validation import validate_date_str
from database.db import get_connection

VALID_HOURS_RANGE = (0, 24)
VALID_QUALITY_RANGE = (1, 5)


class SleepValidationError(ValueError):
    pass


def record_sleep(profile_id: str, hours: float, quality: int | None = None, log_date: str | None = None, notes: str | None = None) -> dict:
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        raise SleepValidationError("hours must be a number")
    lo, hi = VALID_HOURS_RANGE
    if not (lo <= hours <= hi):
        raise SleepValidationError(f"hours must be between {lo} and {hi}, got {hours}")

    if quality is not None:
        try:
            quality = int(quality)
        except (TypeError, ValueError):
            raise SleepValidationError("quality must be an integer")
        lo_q, hi_q = VALID_QUALITY_RANGE
        if not (lo_q <= quality <= hi_q):
            raise SleepValidationError(f"quality must be between {lo_q} and {hi_q}")

    if log_date is not None:
        try:
            validate_date_str("log_date", log_date)
        except ValueError as e:
            raise SleepValidationError(str(e))
    log_date = log_date or dt.date.today().isoformat()
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO sleep_logs (profile_id, log_date, hours, quality, notes) VALUES (?, ?, ?, ?, ?)",
        (profile_id, log_date, hours, quality, notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sleep_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_sleep_history(profile_id: str, days: int = 30) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sleep_logs WHERE profile_id = ? AND log_date >= ? ORDER BY log_date DESC, id DESC",
        (profile_id, since),
    ).fetchall()
    return [dict(r) for r in rows]
