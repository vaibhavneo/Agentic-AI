"""Deterministic daily nutrition totals — sums meals for a profile+date.
Never persisted as its own row: derived fresh from meal_foods so it can
never drift from what was actually logged.
"""
from __future__ import annotations

import datetime as dt

from database.db import get_connection
from nutrition.meal_service import NUTRIENT_FIELDS, calculate_meal_nutrition, list_meals


def calculate_daily_nutrition(profile_id: str, target_date: str | None = None) -> dict:
    target_date = target_date or dt.date.today().isoformat()
    meals = list_meals(profile_id, target_date)

    totals = {f: 0.0 for f in NUTRIENT_FIELDS}
    by_meal = []
    for meal in meals:
        meal_totals = calculate_meal_nutrition(meal["id"], profile_id)
        by_meal.append(meal_totals)
        for f in NUTRIENT_FIELDS:
            totals[f] += meal_totals[f]

    totals = {k: round(v, 2) for k, v in totals.items()}

    conn = get_connection()
    water_row = conn.execute(
        "SELECT COALESCE(SUM(amount_ml), 0) AS total FROM water_logs WHERE profile_id = ? AND log_date = ?",
        (profile_id, target_date),
    ).fetchone()

    return {
        "date": target_date,
        "profile_id": profile_id,
        "totals": totals,
        "water_ml": water_row["total"],
        "meals": by_meal,
        "meal_count": len(meals),
    }


def get_today_nutrition(profile_id: str) -> dict:
    return calculate_daily_nutrition(profile_id, dt.date.today().isoformat())
