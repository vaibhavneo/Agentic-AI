"""Workout logging + weekly rollups. Wearable calorie estimates are treated
as uncertain: exposed as-is for display, but conservative_dietary_credit is
the only value any future auto-crediting feature (e.g. the Fitness Agent)
should feed back into a dietary allowance — never the raw wearable number.
"""
from __future__ import annotations

import datetime as dt

from app.validation import validate_date_str
from database.db import get_connection

VALID_WORKOUT_TYPES = {"cardio", "strength"}
VALID_INTENSITIES = {"light", "moderate", "vigorous"}

VALID_DURATION_MIN_RANGE = (0, 600)
VALID_DISTANCE_KM_RANGE = (0, 500)
VALID_STEPS_RANGE = (0, 100000)
VALID_HR_RANGE = (30, 250)
VALID_RPE_RANGE = (1, 10)
VALID_WEIGHT_KG_RANGE = (0, 500)
VALID_REPS_RANGE = (1, 1000)

# Wearable calorie estimates run high (device algorithms tend to
# over-report); crediting only a fraction back to a dietary allowance avoids
# compounding that overestimate into "ate back more than was really burned."
WEARABLE_CALORIE_CREDIT_FACTOR = 0.75


class ActivityValidationError(ValueError):
    pass


def _check_range(name, value, lo, hi, required=False):
    if value is None:
        if required:
            raise ActivityValidationError(f"{name} is required")
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ActivityValidationError(f"{name} must be a number")
    if not (lo <= v <= hi):
        raise ActivityValidationError(f"{name} must be between {lo} and {hi}, got {v}")
    return v


def conservative_dietary_credit(wearable_calories: float | None) -> float | None:
    if wearable_calories is None:
        return None
    return round(wearable_calories * WEARABLE_CALORIE_CREDIT_FACTOR, 1)


def log_workout(
    profile_id: str,
    workout_type: str,
    activity: str,
    workout_date: str | None = None,
    start_time: str | None = None,
    duration_min: float | None = None,
    distance_km: float | None = None,
    steps: int | None = None,
    avg_hr: int | None = None,
    max_hr: int | None = None,
    rpe: int | None = None,
    intensity: str | None = None,
    wearable_calories: float | None = None,
    notes: str | None = None,
    strength_sets: list[dict] | None = None,
) -> dict:
    if workout_type not in VALID_WORKOUT_TYPES:
        raise ActivityValidationError(f"workout_type must be one of {sorted(VALID_WORKOUT_TYPES)}")
    if not activity or not activity.strip():
        raise ActivityValidationError("activity is required")

    if workout_type == "cardio":
        if intensity is None:
            raise ActivityValidationError("intensity is required for cardio workouts")
        if intensity not in VALID_INTENSITIES:
            raise ActivityValidationError(f"intensity must be one of {sorted(VALID_INTENSITIES)}")
    elif intensity is not None and intensity not in VALID_INTENSITIES:
        raise ActivityValidationError(f"intensity must be one of {sorted(VALID_INTENSITIES)}")

    duration_min = _check_range("duration_min", duration_min, *VALID_DURATION_MIN_RANGE)
    distance_km = _check_range("distance_km", distance_km, *VALID_DISTANCE_KM_RANGE)
    steps = _check_range("steps", steps, *VALID_STEPS_RANGE)
    avg_hr = _check_range("avg_hr", avg_hr, *VALID_HR_RANGE)
    max_hr = _check_range("max_hr", max_hr, *VALID_HR_RANGE)
    rpe = _check_range("rpe", rpe, *VALID_RPE_RANGE)
    wearable_calories = _check_range("wearable_calories", wearable_calories, 0, 10000)

    if workout_date is not None:
        try:
            validate_date_str("workout_date", workout_date)
        except ValueError as e:
            raise ActivityValidationError(str(e))
    workout_date = workout_date or dt.date.today().isoformat()

    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO workouts (
            profile_id, workout_type, activity, workout_date, start_time, duration_min,
            distance_km, steps, avg_hr, max_hr, rpe, intensity, wearable_calories, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            profile_id, workout_type, activity.strip(), workout_date, start_time, duration_min,
            distance_km, steps, avg_hr, max_hr, rpe, intensity, wearable_calories, notes,
        ),
    )
    workout_id = cur.lastrowid

    if strength_sets:
        for i, s in enumerate(strength_sets, start=1):
            if not s.get("exercise_name"):
                raise ActivityValidationError("each strength set needs exercise_name")
            reps = _check_range("reps", s.get("reps"), *VALID_REPS_RANGE, required=True)
            weight_kg = _check_range("weight_kg", s.get("weight_kg"), *VALID_WEIGHT_KG_RANGE)
            set_rpe = _check_range("set rpe", s.get("rpe"), *VALID_RPE_RANGE)
            conn.execute(
                """INSERT INTO strength_sets (workout_id, exercise_name, set_number, reps, weight_kg, rpe)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (workout_id, s["exercise_name"].strip(), s.get("set_number", i), int(reps), weight_kg, set_rpe),
            )

    conn.commit()
    return get_workout(workout_id, profile_id)


def get_workout(workout_id: int, profile_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM workouts WHERE id = ? AND profile_id = ?", (workout_id, profile_id)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["dietary_credit"] = conservative_dietary_credit(d["wearable_calories"])
    if d["workout_type"] == "strength":
        sets = conn.execute(
            "SELECT * FROM strength_sets WHERE workout_id = ? ORDER BY set_number", (workout_id,)
        ).fetchall()
        d["sets"] = [dict(s) for s in sets]
    else:
        d["sets"] = []
    return d


def delete_workout(workout_id: int, profile_id: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM workouts WHERE id = ? AND profile_id = ?", (workout_id, profile_id))
    conn.commit()


def list_workouts(profile_id: str, since_date: str, until_date: str | None = None) -> list[dict]:
    until_date = until_date or dt.date.today().isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT id FROM workouts WHERE profile_id = ? AND workout_date BETWEEN ? AND ? ORDER BY workout_date DESC, id DESC",
        (profile_id, since_date, until_date),
    ).fetchall()
    return [get_workout(r["id"], profile_id) for r in rows]


def get_today_activity(profile_id: str) -> dict:
    today = dt.date.today().isoformat()
    workouts = list_workouts(profile_id, today, today)
    return _summarize(workouts, today, today)


def get_weekly_activity(profile_id: str, week_start: str | None = None) -> dict:
    """week_start defaults to the most recent Monday (inclusive), giving a
    standard Mon-Sun week for comparing against the 150min-moderate /
    75min-vigorous weekly aerobic guideline."""
    if week_start is None:
        today = dt.date.today()
        week_start_date = today - dt.timedelta(days=today.weekday())
    else:
        week_start_date = dt.date.fromisoformat(week_start)
    week_end_date = week_start_date + dt.timedelta(days=6)

    workouts = list_workouts(profile_id, week_start_date.isoformat(), week_end_date.isoformat())
    return _summarize(workouts, week_start_date.isoformat(), week_end_date.isoformat())


def _summarize(workouts: list[dict], start_date: str, end_date: str) -> dict:
    moderate_minutes = sum(w["duration_min"] or 0 for w in workouts if w["workout_type"] == "cardio" and w["intensity"] == "moderate")
    vigorous_minutes = sum(w["duration_min"] or 0 for w in workouts if w["workout_type"] == "cardio" and w["intensity"] == "vigorous")
    light_minutes = sum(w["duration_min"] or 0 for w in workouts if w["workout_type"] == "cardio" and w["intensity"] == "light")

    strength_days = len({w["workout_date"] for w in workouts if w["workout_type"] == "strength"})
    total_distance_km = round(sum(w["distance_km"] or 0 for w in workouts), 2)
    total_steps = sum(w["steps"] or 0 for w in workouts)
    total_wearable_calories = round(sum(w["wearable_calories"] or 0 for w in workouts), 1)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "workout_count": len(workouts),
        "moderate_minutes": round(moderate_minutes, 1),
        "vigorous_minutes": round(vigorous_minutes, 1),
        "light_minutes": round(light_minutes, 1),
        # CDC guideline treats 1 vigorous minute ~ 2 moderate minutes toward
        # the weekly 150-moderate-equivalent target.
        "weighted_aerobic_minutes": round(moderate_minutes + 2 * vigorous_minutes, 1),
        "strength_days": strength_days,
        "total_distance_km": total_distance_km,
        "total_steps": total_steps,
        "total_wearable_calories": total_wearable_calories,
        "conservative_dietary_credit": conservative_dietary_credit(total_wearable_calories),
        "workouts": workouts,
    }
