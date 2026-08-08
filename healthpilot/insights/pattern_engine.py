"""Exploratory cross-domain pattern analysis. Every association is computed
with plain arithmetic (Pearson correlation + simple linear slope) over real
stored data — never an LLM guess. Anything below MIN_SAMPLE_SIZE is reported
as insufficient_data rather than shown with false confidence, and every
computed result carries an explicit "associated with, not caused by" caveat.

MIN_SAMPLE_SIZE is deliberately low (5) so a fresh profile with a couple
weeks of logging can see *something* — production deployments with more
history should raise it (10-14+) for a more defensible correlation.
"""
from __future__ import annotations

import datetime as dt
import statistics

from exercise.activity_service import get_weekly_activity, list_workouts
from nutrition.daily_service import calculate_daily_nutrition
from nutrition.meal_service import list_meals
from nutrition.targets import get_active_target
from vitals.bp_service import get_bp_history
from vitals.sleep_service import get_sleep_history
from vitals.weight_service import get_weight_history

MIN_SAMPLE_SIZE = 5
DEFAULT_WINDOW_DAYS = 60
DEFAULT_WINDOW_WEEKS = 8

CAVEAT = "Associated with, not necessarily caused by — exploratory only, not a diagnosis."


def _pearson(pairs: list[tuple[float, float]]) -> dict | None:
    n = len(pairs)
    if n < 2:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    std_x, std_y = statistics.pstdev(xs), statistics.pstdev(ys)
    if std_x == 0 or std_y == 0:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / n
    r = cov / (std_x * std_y)
    var_x = statistics.pvariance(xs)
    slope = cov / var_x if var_x > 0 else None
    return {"r": round(r, 3), "slope": round(slope, 4) if slope is not None else None}


def _association_result(name: str, pairs: list[tuple[float, float]], window_days: int, description: str) -> dict:
    n = len(pairs)
    result = {
        "name": name,
        "description": description,
        "sample_size": n,
        "window_days": window_days,
        "min_sample_size": MIN_SAMPLE_SIZE,
    }
    if n < MIN_SAMPLE_SIZE:
        result["status"] = "insufficient_data"
        result["correlation"] = None
        result["effect_estimate"] = None
        return result

    stats = _pearson(pairs)
    if stats is None:
        result["status"] = "no_variation"
        result["correlation"] = None
        result["effect_estimate"] = None
        return result

    result["status"] = "computed"
    result["correlation"] = stats["r"]
    result["effect_estimate"] = stats["slope"]
    result["caveat"] = CAVEAT
    return result


def _bp_by_date(profile_id: str, days: int) -> dict[str, float]:
    history = get_bp_history(profile_id, days)
    by_date: dict[str, list[float]] = {}
    for r in history:
        by_date.setdefault(r["reading_date"], []).append(r["average_systolic"])
    return {d: statistics.mean(v) for d, v in by_date.items()}


def sodium_vs_next_day_bp(profile_id: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    bp_by_date = _bp_by_date(profile_id, days + 1)
    today = dt.date.today()
    pairs = []
    for offset in range(1, days + 1):
        d = today - dt.timedelta(days=offset)
        next_d = d + dt.timedelta(days=1)
        daily = calculate_daily_nutrition(profile_id, d.isoformat())
        if daily["meal_count"] == 0:
            continue
        bp = bp_by_date.get(next_d.isoformat())
        if bp is None:
            continue
        pairs.append((daily["totals"]["sodium_mg"], bp))
    return _association_result("sodium_vs_next_day_bp", pairs, days, "Daily sodium intake vs the next day's average BP")


def sleep_vs_morning_bp(profile_id: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    bp_by_date = _bp_by_date(profile_id, days)
    sleep_history = get_sleep_history(profile_id, days)
    pairs = []
    for s in sleep_history:
        bp = bp_by_date.get(s["log_date"])
        if bp is None:
            continue
        pairs.append((s["hours"], bp))
    return _association_result("sleep_vs_morning_bp", pairs, days, "Sleep hours vs that same morning's average BP")


def exercise_vs_bp(profile_id: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    bp_by_date = _bp_by_date(profile_id, days)
    today = dt.date.today()
    pairs = []
    for offset in range(days):
        d = today - dt.timedelta(days=offset)
        bp = bp_by_date.get(d.isoformat())
        if bp is None:
            continue
        workouts = list_workouts(profile_id, d.isoformat(), d.isoformat())
        minutes = sum(w["duration_min"] or 0 for w in workouts if w["workout_type"] == "cardio")
        pairs.append((minutes, bp))
    return _association_result("exercise_vs_bp", pairs, days, "Same-day cardio minutes vs average BP")


def restaurant_meals_vs_bp(profile_id: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    bp_by_date = _bp_by_date(profile_id, days)
    today = dt.date.today()
    pairs = []
    for offset in range(days):
        d = (today - dt.timedelta(days=offset)).isoformat()
        meals = list_meals(profile_id, d)
        if not meals:
            continue
        bp = bp_by_date.get(d)
        if bp is None:
            continue
        restaurant_count = sum(1 for m in meals if m["restaurant"])
        pairs.append((restaurant_count, bp))
    return _association_result("restaurant_meals_vs_bp", pairs, days, "Same-day restaurant meal count vs average BP")


def weight_vs_bp(profile_id: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    bp_by_date = _bp_by_date(profile_id, days)
    weight_history = get_weight_history(profile_id, days)
    pairs = []
    for w in weight_history:
        bp = bp_by_date.get(w["log_date"])
        if bp is None:
            continue
        pairs.append((w["weight_kg"], bp))
    return _association_result("weight_vs_bp", pairs, days, "Same-day body weight vs average BP")


def activity_vs_sleep(profile_id: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    sleep_history = get_sleep_history(profile_id, days + 1)
    sleep_by_date = {s["log_date"]: s["hours"] for s in sleep_history}
    today = dt.date.today()
    pairs = []
    for offset in range(1, days + 1):
        d = today - dt.timedelta(days=offset)
        next_d = d + dt.timedelta(days=1)
        sleep = sleep_by_date.get(next_d.isoformat())
        if sleep is None:
            continue
        workouts = list_workouts(profile_id, d.isoformat(), d.isoformat())
        minutes = sum(w["duration_min"] or 0 for w in workouts if w["workout_type"] == "cardio")
        pairs.append((minutes, sleep))
    return _association_result("activity_vs_sleep", pairs, days, "Daytime cardio minutes vs that night's sleep hours")


def protein_adequacy_vs_strength_days(profile_id: str, weeks: int = DEFAULT_WINDOW_WEEKS) -> dict:
    target = get_active_target(profile_id)
    if target is None or not target.get("protein_g"):
        return _association_result("protein_adequacy_vs_strength_days", [], weeks * 7, "Weekly protein-target adequacy vs strength training days")

    today = dt.date.today()
    this_monday = today - dt.timedelta(days=today.weekday())
    pairs = []
    for w in range(1, weeks + 1):
        week_start = this_monday - dt.timedelta(days=7 * w)
        daily_proteins = []
        for i in range(7):
            d = (week_start + dt.timedelta(days=i)).isoformat()
            daily = calculate_daily_nutrition(profile_id, d)
            if daily["meal_count"] > 0:
                daily_proteins.append(daily["totals"]["protein_g"])
        if not daily_proteins:
            continue
        avg_protein_ratio = round(statistics.mean(daily_proteins) / target["protein_g"], 3)
        weekly_activity = get_weekly_activity(profile_id, week_start.isoformat())
        pairs.append((avg_protein_ratio, weekly_activity["strength_days"]))
    return _association_result("protein_adequacy_vs_strength_days", pairs, weeks * 7, "Weekly protein-target adequacy vs strength training days")


def analyze_health_patterns(profile_id: str) -> dict:
    return {
        "generated_at": dt.datetime.now().isoformat(),
        "associations": [
            sodium_vs_next_day_bp(profile_id),
            sleep_vs_morning_bp(profile_id),
            exercise_vs_bp(profile_id),
            restaurant_meals_vs_bp(profile_id),
            weight_vs_bp(profile_id),
            activity_vs_sleep(profile_id),
            protein_adequacy_vs_strength_days(profile_id),
        ],
    }
