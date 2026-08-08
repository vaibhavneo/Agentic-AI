"""Smaller optional daily vitals: resting HR, waist, HRV, SpO2. All fields
optional — a check-in can log any subset of them."""
from __future__ import annotations

import datetime as dt

from app.validation import validate_date_str
from database.db import get_connection

VALID_RESTING_HR_RANGE = (25, 220)
VALID_WAIST_CM_RANGE = (30, 250)
VALID_HRV_MS_RANGE = (1, 300)
VALID_SPO2_PCT_RANGE = (50, 100)


class OtherVitalsValidationError(ValueError):
    pass


def _optional_range_check(name, value, lo, hi):
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise OtherVitalsValidationError(f"{name} must be a number")
    if not (lo <= v <= hi):
        raise OtherVitalsValidationError(f"{name} must be between {lo} and {hi}, got {v}")
    return v


def record_other_vitals(
    profile_id: str,
    resting_hr: int | None = None,
    waist_cm: float | None = None,
    hrv_ms: float | None = None,
    spo2_pct: float | None = None,
    log_date: str | None = None,
    notes: str | None = None,
) -> dict:
    resting_hr = _optional_range_check("resting_hr", resting_hr, *VALID_RESTING_HR_RANGE)
    waist_cm = _optional_range_check("waist_cm", waist_cm, *VALID_WAIST_CM_RANGE)
    hrv_ms = _optional_range_check("hrv_ms", hrv_ms, *VALID_HRV_MS_RANGE)
    spo2_pct = _optional_range_check("spo2_pct", spo2_pct, *VALID_SPO2_PCT_RANGE)

    if all(v is None for v in (resting_hr, waist_cm, hrv_ms, spo2_pct)):
        raise OtherVitalsValidationError("at least one vital must be provided")

    if log_date is not None:
        try:
            validate_date_str("log_date", log_date)
        except ValueError as e:
            raise OtherVitalsValidationError(str(e))
    log_date = log_date or dt.date.today().isoformat()
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO other_vitals_logs (profile_id, log_date, resting_hr, waist_cm, hrv_ms, spo2_pct, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (profile_id, log_date, resting_hr, waist_cm, hrv_ms, spo2_pct, notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM other_vitals_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_other_vitals_history(profile_id: str, days: int = 30) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM other_vitals_logs WHERE profile_id = ? AND log_date >= ? ORDER BY log_date DESC, id DESC",
        (profile_id, since),
    ).fetchall()
    return [dict(r) for r in rows]
