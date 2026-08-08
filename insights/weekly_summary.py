"""Weekly trend summary for the Today page's 'This week' section: average
sodium/protein/fiber, BP/weight/exercise trends, sleep average, and a
week-over-week calorie comparison. All arithmetic over already-built
service functions — nothing new persisted here.
"""
from __future__ import annotations

import datetime as dt
import statistics

from exercise.activity_service import get_weekly_activity
from nutrition.daily_service import calculate_daily_nutrition
from vitals.bp_service import calculate_bp_average, calculate_bp_trend
from vitals.sleep_service import get_sleep_history
from vitals.weight_service import calculate_weight_trend


def _avg_nutrition_over_days(profile_id: str, days: list[str]) -> dict:
    values = {"calories_kcal": [], "protein_g": [], "fiber_g": [], "sodium_mg": []}
    for d in days:
        daily = calculate_daily_nutrition(profile_id, d)
        if daily["meal_count"] == 0:
            continue
        for k in values:
            values[k].append(daily["totals"][k])
    return {k: round(statistics.mean(v), 1) if v else None for k, v in values.items()}


def get_weekly_summary(profile_id: str) -> dict:
    today = dt.date.today()
    this_week_days = [(today - dt.timedelta(days=i)).isoformat() for i in range(7)]
    last_week_days = [(today - dt.timedelta(days=i)).isoformat() for i in range(7, 14)]

    this_week_avg = _avg_nutrition_over_days(profile_id, this_week_days)
    last_week_avg = _avg_nutrition_over_days(profile_id, last_week_days)

    calorie_change = None
    if this_week_avg["calories_kcal"] is not None and last_week_avg["calories_kcal"] is not None:
        calorie_change = round(this_week_avg["calories_kcal"] - last_week_avg["calories_kcal"], 1)

    sleep_history = get_sleep_history(profile_id, 7)
    avg_sleep = round(statistics.mean(h["hours"] for h in sleep_history), 1) if sleep_history else None

    return {
        "avg_sodium_mg": this_week_avg["sodium_mg"],
        "avg_protein_g": this_week_avg["protein_g"],
        "avg_fiber_g": this_week_avg["fiber_g"],
        "avg_calories_kcal": this_week_avg["calories_kcal"],
        "calorie_change_vs_last_week": calorie_change,
        "bp_average_7day": calculate_bp_average(profile_id, days=7),
        "bp_trend_30day": calculate_bp_trend(profile_id, days=30),
        "weight_trend_30day": calculate_weight_trend(profile_id, days=30),
        "activity_this_week": get_weekly_activity(profile_id),
        "avg_sleep_hours": avg_sleep,
        "nights_sleep_logged": len(sleep_history),
    }
