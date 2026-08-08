"""BP recording + history/average/trend. This is the integration point
between the pure safety/bp_safety.py engine and persistence: every
warning-or-worse reading gets an audit entry in safety_events, and every
reading stores the classification it received at record time so history
never has to re-derive (and potentially re-argue with) a past verdict —
except the message text, which is cheap to regenerate deterministically
from (category, symptoms) and isn't duplicated in storage.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics

from app.validation import validate_date_str
from database.db import get_connection
from safety.bp_safety import BPSafetyError, evaluate_bp_reading
from safety.constants import (
    VALID_BP_DIASTOLIC_RANGE,
    VALID_BP_PULSE_RANGE,
    VALID_BP_SYSTOLIC_RANGE,
)
from safety.events import log_safety_event


class BPValidationError(ValueError):
    pass


def _validate_reading_value(name: str, value, lo, hi):
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise BPValidationError(f"{name} must be an integer")
    if not (lo <= v <= hi):
        raise BPValidationError(f"{name} must be between {lo} and {hi}, got {v}")
    return v


def record_bp(
    profile_id: str,
    systolic_1: int,
    diastolic_1: int,
    pulse_1: int | None = None,
    systolic_2: int | None = None,
    diastolic_2: int | None = None,
    pulse_2: int | None = None,
    symptoms: list[str] | None = None,
    reading_date: str | None = None,
    reading_time: str | None = None,
    notes: str | None = None,
) -> dict:
    s1 = _validate_reading_value("systolic_1", systolic_1, *VALID_BP_SYSTOLIC_RANGE)
    d1 = _validate_reading_value("diastolic_1", diastolic_1, *VALID_BP_DIASTOLIC_RANGE)
    p1 = _validate_reading_value("pulse_1", pulse_1, *VALID_BP_PULSE_RANGE) if pulse_1 is not None else None
    if d1 >= s1:
        raise BPValidationError(f"diastolic_1 ({d1}) cannot be greater than or equal to systolic_1 ({s1})")

    s2 = d2 = p2 = None
    if systolic_2 is not None or diastolic_2 is not None:
        s2 = _validate_reading_value("systolic_2", systolic_2, *VALID_BP_SYSTOLIC_RANGE)
        d2 = _validate_reading_value("diastolic_2", diastolic_2, *VALID_BP_DIASTOLIC_RANGE)
        p2 = _validate_reading_value("pulse_2", pulse_2, *VALID_BP_PULSE_RANGE) if pulse_2 is not None else None
        if d2 >= s2:
            raise BPValidationError(f"diastolic_2 ({d2}) cannot be greater than or equal to systolic_2 ({s2})")

    avg_systolic = round((s1 + s2) / 2) if s2 is not None else s1
    avg_diastolic = round((d1 + d2) / 2) if d2 is not None else d1

    try:
        evaluation = evaluate_bp_reading(avg_systolic, avg_diastolic, symptoms)
    except BPSafetyError as e:
        raise BPValidationError(str(e))

    if reading_date is not None:
        try:
            validate_date_str("reading_date", reading_date)
        except ValueError as e:
            raise BPValidationError(str(e))
    reading_date = reading_date or dt.date.today().isoformat()

    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO bp_readings (
            profile_id, reading_date, reading_time, systolic_1, diastolic_1, pulse_1,
            systolic_2, diastolic_2, pulse_2, symptoms_json, notes, category, urgency, emergency
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            profile_id, reading_date, reading_time, s1, d1, p1, s2, d2, p2,
            json.dumps(evaluation["symptoms"]), notes,
            evaluation["category"], evaluation["urgency"], int(evaluation["emergency"]),
        ),
    )
    conn.commit()
    reading_id = cur.lastrowid

    if evaluation["urgency"] != "info":
        log_safety_event(
            profile_id,
            event_type="bp_reading",
            severity=evaluation["urgency"],
            message=evaluation["message"],
            context={
                "reading_id": reading_id,
                "category": evaluation["category"],
                "systolic": avg_systolic,
                "diastolic": avg_diastolic,
                "emergency": evaluation["emergency"],
                "symptoms": evaluation["symptoms"],
            },
        )

    return get_bp_reading(reading_id, profile_id)


def classify_time_of_day(reading_time: str | None) -> str:
    """Deterministic morning/evening split from an HH:MM reading_time —
    before noon is 'morning', noon or later is 'evening'. No reading_time
    logged at all is 'unspecified', not guessed."""
    if not reading_time:
        return "unspecified"
    try:
        hour = int(reading_time.split(":")[0])
    except (ValueError, IndexError):
        return "unspecified"
    return "morning" if hour < 12 else "evening"


def _row_to_reading(row) -> dict:
    d = dict(row)
    d["symptoms"] = json.loads(d.pop("symptoms_json"))
    d["average_systolic"] = round((d["systolic_1"] + d["systolic_2"]) / 2) if d["systolic_2"] else d["systolic_1"]
    d["average_diastolic"] = round((d["diastolic_1"] + d["diastolic_2"]) / 2) if d["diastolic_2"] else d["diastolic_1"]
    d["message"] = evaluate_bp_reading(d["average_systolic"], d["average_diastolic"], d["symptoms"])["message"]
    d["time_of_day"] = classify_time_of_day(d.get("reading_time"))
    return d


def get_bp_reading(reading_id: int, profile_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM bp_readings WHERE id = ? AND profile_id = ?", (reading_id, profile_id)
    ).fetchone()
    return _row_to_reading(row) if row else None


def get_latest_bp_reading(profile_id: str) -> dict | None:
    """Most recent reading regardless of date — distinct from 'today's
    reading.' Today pages/dashboards want 'latest' even if the last log was
    yesterday, not an empty state just because nothing was logged today."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM bp_readings WHERE profile_id = ? ORDER BY reading_date DESC, id DESC LIMIT 1",
        (profile_id,),
    ).fetchone()
    return _row_to_reading(row) if row else None


def get_bp_history(profile_id: str, days: int = 30) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM bp_readings WHERE profile_id = ? AND reading_date >= ? ORDER BY reading_date DESC, id DESC",
        (profile_id, since),
    ).fetchall()
    return [_row_to_reading(r) for r in rows]


def calculate_bp_average(profile_id: str, days: int = 7) -> dict:
    readings = get_bp_history(profile_id, days)
    if not readings:
        return {"days": days, "sample_size": 0, "avg_systolic": None, "avg_diastolic": None}
    avg_systolic = round(statistics.mean(r["average_systolic"] for r in readings), 1)
    avg_diastolic = round(statistics.mean(r["average_diastolic"] for r in readings), 1)
    return {
        "days": days,
        "sample_size": len(readings),
        "avg_systolic": avg_systolic,
        "avg_diastolic": avg_diastolic,
        "systolic_variability": round(statistics.pstdev(r["average_systolic"] for r in readings), 1) if len(readings) > 1 else 0,
        "diastolic_variability": round(statistics.pstdev(r["average_diastolic"] for r in readings), 1) if len(readings) > 1 else 0,
    }


def get_today_bp_average(profile_id: str) -> dict:
    """Today's average, distinct from the 7-day/30-day rolling averages —
    a thin, clearly-named wrapper so callers don't have to know that
    days=1 means 'just today'."""
    return calculate_bp_average(profile_id, days=1)


def calculate_bp_trend(profile_id: str, days: int = 30) -> dict:
    """Splits the window into an older half and a more-recent half and
    compares their averages — a simple, easily-audited trend signal rather
    than a fitted model. Requires at least 4 readings (2 per half) to avoid
    a 'trend' being read into 1-2 noisy data points."""
    readings = get_bp_history(profile_id, days)
    if len(readings) < 4:
        return {
            "days": days, "sample_size": len(readings), "direction": "insufficient_data",
            "systolic_delta": None, "diastolic_delta": None,
        }

    chronological = list(reversed(readings))  # oldest first
    midpoint = len(chronological) // 2
    older, recent = chronological[:midpoint], chronological[midpoint:]

    older_systolic = statistics.mean(r["average_systolic"] for r in older)
    recent_systolic = statistics.mean(r["average_systolic"] for r in recent)
    older_diastolic = statistics.mean(r["average_diastolic"] for r in older)
    recent_diastolic = statistics.mean(r["average_diastolic"] for r in recent)

    systolic_delta = round(recent_systolic - older_systolic, 1)
    diastolic_delta = round(recent_diastolic - older_diastolic, 1)

    if systolic_delta > 3 or diastolic_delta > 2:
        direction = "rising"
    elif systolic_delta < -3 or diastolic_delta < -2:
        direction = "falling"
    else:
        direction = "stable"

    return {
        "days": days,
        "sample_size": len(readings),
        "direction": direction,
        "systolic_delta": systolic_delta,
        "diastolic_delta": diastolic_delta,
    }
