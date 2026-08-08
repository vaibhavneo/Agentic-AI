"""'Export My Data' — one JSON document covering every table scoped to a
profile, built entirely from parameterized queries against profile_id
(never string-interpolated). Streamed directly in the HTTP response, never
written to disk under a profile-supplied name — see app/csv_import.py for
the same reasoning applied to imports.
"""
from __future__ import annotations

import datetime as dt

from app.medication import list_medications
from app.profile import get_profile
from database.db import get_connection
from exercise.activity_service import list_workouts
from nutrition.meal_service import list_meals
from safety.events import list_safety_events
from vitals.bp_service import get_bp_history
from vitals.other_vitals_service import get_other_vitals_history
from vitals.sleep_service import get_sleep_history
from vitals.weight_service import get_weight_history


def _all_medication_logs(profile_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM medication_logs WHERE profile_id = ? ORDER BY log_date", (profile_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _all_meals(profile_id: str) -> list[dict]:
    conn = get_connection()
    dates = conn.execute(
        "SELECT DISTINCT meal_date FROM meals WHERE profile_id = ? ORDER BY meal_date", (profile_id,)
    ).fetchall()
    meals = []
    for d in dates:
        meals.extend(list_meals(profile_id, d["meal_date"]))
    return meals


def _all_nutrition_targets(profile_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM nutrition_targets WHERE profile_id = ? ORDER BY effective_date", (profile_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _all_water_logs(profile_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM water_logs WHERE profile_id = ? ORDER BY log_date", (profile_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _all_weekly_plans(profile_id: str) -> list[dict]:
    conn = get_connection()
    plans = conn.execute(
        "SELECT * FROM weekly_plans WHERE profile_id = ? ORDER BY week_start", (profile_id,)
    ).fetchall()
    result = []
    for plan in plans:
        days = conn.execute(
            "SELECT * FROM plan_days WHERE weekly_plan_id = ? ORDER BY day_index", (plan["id"],)
        ).fetchall()
        day_list = []
        for day in days:
            meals = conn.execute("SELECT * FROM plan_meals WHERE plan_day_id = ?", (day["id"],)).fetchall()
            meal_list = []
            for meal in meals:
                items = conn.execute(
                    "SELECT * FROM plan_meal_foods WHERE plan_meal_id = ?", (meal["id"],)
                ).fetchall()
                meal_list.append({**dict(meal), "items": [dict(i) for i in items]})
            day_list.append({**dict(day), "meals": meal_list})
        result.append({**dict(plan), "days": day_list})
    return result


def export_profile_data(profile_id: str) -> dict:
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"no such profile: {profile_id}")

    return {
        "exported_at": dt.datetime.now().isoformat(),
        "profile": profile,
        "medications": list_medications(profile_id, active_only=False),
        "medication_logs": _all_medication_logs(profile_id),
        "meals": _all_meals(profile_id),
        "nutrition_targets": _all_nutrition_targets(profile_id),
        "water_logs": _all_water_logs(profile_id),
        "bp_readings": get_bp_history(profile_id, days=36500),
        "weight_logs": get_weight_history(profile_id, days=36500),
        "sleep_logs": get_sleep_history(profile_id, days=36500),
        "other_vitals_logs": get_other_vitals_history(profile_id, days=36500),
        "workouts": list_workouts(profile_id, "1970-01-01"),
        "weekly_plans": _all_weekly_plans(profile_id),
        "safety_events": list_safety_events(profile_id, limit=100000),
    }
