"""Component health scores — deliberately NOT combined into one opaque
number, and never a score of the health condition itself (no "BP score").
Each component scores a behavior the user controls (nutrition quality,
sodium management, protein adequacy, fiber, activity, strength, sleep, plan
adherence) over the last 7 days, with its raw inputs attached so the number
is never a black box.
"""
from __future__ import annotations

import datetime as dt
import statistics

from exercise.activity_service import get_weekly_activity
from nutrition.daily_service import calculate_daily_nutrition
from nutrition.meal_service import list_meals
from nutrition.targets import get_active_target
from vitals.sleep_service import get_sleep_history

WINDOW_DAYS = 7


def _clamp(value: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, value))


def _last_n_days(n: int) -> list[str]:
    today = dt.date.today()
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(n)]


def _nutrition_quality(profile_id: str, target: dict | None) -> dict:
    days = _last_n_days(WINDOW_DAYS)
    logged_days = 0
    on_target_days = 0
    for d in days:
        daily = calculate_daily_nutrition(profile_id, d)
        if daily["meal_count"] == 0:
            continue
        logged_days += 1
        if target and abs(daily["totals"]["calories_kcal"] - target["calories"]) <= target["calories"] * 0.20:
            on_target_days += 1
    score = _clamp(100 * on_target_days / logged_days) if logged_days else 0
    return {"score": round(score, 1), "inputs": {"days_logged": logged_days, "days_within_20pct_of_calorie_target": on_target_days, "window_days": WINDOW_DAYS}}


def _sodium_management(profile_id: str, target: dict | None) -> dict:
    days = _last_n_days(WINDOW_DAYS)
    logged_days = 0
    under_ceiling_days = 0
    sodium_ceiling = target["sodium_mg"] if target else 2300
    for d in days:
        daily = calculate_daily_nutrition(profile_id, d)
        if daily["meal_count"] == 0:
            continue
        logged_days += 1
        if daily["totals"]["sodium_mg"] <= sodium_ceiling:
            under_ceiling_days += 1
    score = _clamp(100 * under_ceiling_days / logged_days) if logged_days else 0
    return {"score": round(score, 1), "inputs": {"days_logged": logged_days, "days_under_sodium_ceiling": under_ceiling_days, "sodium_ceiling_mg": sodium_ceiling}}


def _protein_adequacy(profile_id: str, target: dict | None) -> dict:
    if not target or not target.get("protein_g"):
        return {"score": 0, "inputs": {"reason": "no protein target set"}}
    days = _last_n_days(WINDOW_DAYS)
    ratios = []
    for d in days:
        daily = calculate_daily_nutrition(profile_id, d)
        if daily["meal_count"] == 0:
            continue
        ratios.append(daily["totals"]["protein_g"] / target["protein_g"])
    if not ratios:
        return {"score": 0, "inputs": {"days_logged": 0}}
    avg_ratio = statistics.mean(ratios)
    return {"score": round(_clamp(avg_ratio * 100), 1), "inputs": {"days_logged": len(ratios), "avg_protein_g": round(statistics.mean([r * target["protein_g"] for r in ratios]), 1), "target_protein_g": target["protein_g"]}}


def _fiber(profile_id: str, target: dict | None) -> dict:
    if not target:
        return {"score": 0, "inputs": {"reason": "no target set"}}
    days = _last_n_days(WINDOW_DAYS)
    ratios = []
    for d in days:
        daily = calculate_daily_nutrition(profile_id, d)
        if daily["meal_count"] == 0:
            continue
        ratios.append(daily["totals"]["fiber_g"] / target["fiber_g"])
    if not ratios:
        return {"score": 0, "inputs": {"days_logged": 0}}
    avg_ratio = statistics.mean(ratios)
    return {"score": round(_clamp(avg_ratio * 100), 1), "inputs": {"days_logged": len(ratios), "avg_fiber_g": round(statistics.mean([r * target["fiber_g"] for r in ratios]), 1), "target_fiber_g": target["fiber_g"]}}


def _activity(profile_id: str) -> dict:
    weekly = get_weekly_activity(profile_id)
    score = _clamp(100 * weekly["weighted_aerobic_minutes"] / 150)
    return {"score": round(score, 1), "inputs": {"weighted_aerobic_minutes": weekly["weighted_aerobic_minutes"], "guideline_minutes": 150}}


def _strength(profile_id: str) -> dict:
    weekly = get_weekly_activity(profile_id)
    score = _clamp(100 * weekly["strength_days"] / 2)
    return {"score": round(score, 1), "inputs": {"strength_days": weekly["strength_days"], "guideline_days": 2}}


def _sleep(profile_id: str) -> dict:
    history = get_sleep_history(profile_id, WINDOW_DAYS)
    if not history:
        return {"score": 0, "inputs": {"nights_logged": 0}}
    avg_hours = statistics.mean(h["hours"] for h in history)
    score = _clamp(100 * avg_hours / 8)
    return {"score": round(score, 1), "inputs": {"nights_logged": len(history), "avg_hours": round(avg_hours, 1), "guideline_hours": 8}}


def _plan_adherence(profile_id: str) -> dict:
    """Approximation: of the last 7 days, how many had at least one meal
    actually logged (nutrition.meals), regardless of whether it matched a
    plan. HealthPilot doesn't yet link a specific planned meal to the log
    entry that fulfilled it — see HANDOFF.md — so this measures logging
    consistency as a proxy for adherence, not a verified plan match."""
    days = _last_n_days(WINDOW_DAYS)
    logged_days = sum(1 for d in days if list_meals(profile_id, d))
    score = _clamp(100 * logged_days / WINDOW_DAYS)
    return {"score": round(score, 1), "inputs": {"days_with_a_logged_meal": logged_days, "window_days": WINDOW_DAYS, "note": "proxy: logging consistency, not verified plan match"}}


def compute_health_score(profile_id: str) -> dict:
    target = get_active_target(profile_id)
    return {
        "window_days": WINDOW_DAYS,
        "components": {
            "nutrition_quality": _nutrition_quality(profile_id, target),
            "sodium_management": _sodium_management(profile_id, target),
            "protein_adequacy": _protein_adequacy(profile_id, target),
            "fiber": _fiber(profile_id, target),
            "activity": _activity(profile_id),
            "strength": _strength(profile_id),
            "sleep": _sleep(profile_id),
            "plan_adherence": _plan_adherence(profile_id),
        },
    }
