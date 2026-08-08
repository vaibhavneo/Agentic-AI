"""Persisted weekly plans. Everything here operates on ONE meal or ONE day
at a time and writes only that slice back to the database — generating a
whole week never touches an existing plan_meal, and swapping one meal never
regenerates the rest of the week (see swap_meal / regenerate_day).
"""
from __future__ import annotations

import datetime as dt

from database.db import get_connection
from meal_planning.daily_planner import (
    MealPlanValidationError,
    _build_meal,
    _excluded_terms,
    calorie_shares,
    determine_meal_slots,
    generate_daily_plan,
)
from meal_planning.templates import MAX_TEMPLATE_ATTEMPTS, get_template
from nutrition.food_service import get_food, get_food_by_external_id, resolve_serving_grams
from nutrition.meal_service import NUTRIENT_FIELDS
from nutrition.targets import compute_nutrition_targets, get_active_target


class PlanNotFoundError(ValueError):
    pass


def _week_start(week_start: str | None) -> dt.date:
    if week_start:
        try:
            return dt.date.fromisoformat(week_start)
        except ValueError:
            raise MealPlanValidationError(f"week_start must be a valid YYYY-MM-DD date, got {week_start!r}")
    today = dt.date.today()
    return today - dt.timedelta(days=today.weekday())


def _persist_meal(conn, plan_day_id: int, meal: dict, source: str = "generated", locked: bool = False) -> int:
    cur = conn.execute(
        "INSERT INTO plan_meals (plan_day_id, meal_type, locked, source) VALUES (?, ?, ?, ?)",
        (plan_day_id, meal["meal_type"], int(locked), source),
    )
    plan_meal_id = cur.lastrowid
    for item in meal.get("items", []):
        conn.execute(
            "INSERT INTO plan_meal_foods (plan_meal_id, food_id, serving_id, quantity, grams) VALUES (?, ?, ?, ?, ?)",
            (plan_meal_id, item["food_id"], item["serving_id"], item["quantity"], item["grams"]),
        )
    return plan_meal_id


def create_weekly_plan(profile: dict, week_start: str | None = None) -> dict:
    week_start_date = _week_start(week_start)
    target = get_active_target(profile["id"]) or compute_nutrition_targets(profile)

    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM weekly_plans WHERE profile_id = ? AND week_start = ?",
        (profile["id"], week_start_date.isoformat()),
    ).fetchone()
    if existing:
        raise MealPlanValidationError(f"a plan for week {week_start_date.isoformat()} already exists for this profile")

    cur = conn.execute(
        "INSERT INTO weekly_plans (profile_id, week_start) VALUES (?, ?)",
        (profile["id"], week_start_date.isoformat()),
    )
    weekly_plan_id = cur.lastrowid

    for day_index in range(7):
        day_date = (week_start_date + dt.timedelta(days=day_index)).isoformat()
        day_cur = conn.execute(
            "INSERT INTO plan_days (weekly_plan_id, day_date, day_index) VALUES (?, ?, ?)",
            (weekly_plan_id, day_date, day_index),
        )
        plan_day_id = day_cur.lastrowid

        day_plan = generate_daily_plan(profile, target)  # raises MealPlanValidationError if unsatisfiable
        for meal in day_plan["meals"]:
            _persist_meal(conn, plan_day_id, meal)

    conn.commit()
    return get_weekly_plan(profile["id"], week_start_date.isoformat())


def _load_plan_meal(conn, plan_meal_id: int) -> dict:
    meal_row = conn.execute("SELECT * FROM plan_meals WHERE id = ?", (plan_meal_id,)).fetchone()
    items_rows = conn.execute(
        "SELECT * FROM plan_meal_foods WHERE plan_meal_id = ?", (plan_meal_id,)
    ).fetchall()
    items = []
    for r in items_rows:
        food = get_food(r["food_id"])
        grams = r["grams"]
        items.append({
            "food_id": food["id"], "food_name": food["name"], "serving_id": r["serving_id"],
            "quantity": r["quantity"], "grams": grams,
            **{f: round(food[f] * grams / 100, 2) for f in NUTRIENT_FIELDS},
        })
    totals = {f: round(sum(i[f] for i in items), 2) for f in NUTRIENT_FIELDS}
    d = dict(meal_row)
    d["items"] = items
    d["totals"] = totals
    return d


def get_weekly_plan(profile_id: str, week_start: str) -> dict:
    conn = get_connection()
    plan_row = conn.execute(
        "SELECT * FROM weekly_plans WHERE profile_id = ? AND week_start = ?", (profile_id, week_start)
    ).fetchone()
    if plan_row is None:
        raise PlanNotFoundError(f"no plan for week {week_start}")

    days = conn.execute(
        "SELECT * FROM plan_days WHERE weekly_plan_id = ? ORDER BY day_index", (plan_row["id"],)
    ).fetchall()
    result_days = []
    for day in days:
        meal_rows = conn.execute(
            "SELECT id FROM plan_meals WHERE plan_day_id = ? ORDER BY id", (day["id"],)
        ).fetchall()
        meals = [_load_plan_meal(conn, m["id"]) for m in meal_rows]
        result_days.append({"id": day["id"], "day_date": day["day_date"], "day_index": day["day_index"], "meals": meals})

    return {"id": plan_row["id"], "profile_id": profile_id, "week_start": week_start, "days": result_days}


def _get_plan_meal_or_raise(conn, plan_meal_id: int, profile_id: str) -> dict:
    row = conn.execute(
        """SELECT pm.*, pd.day_date, wp.profile_id FROM plan_meals pm
           JOIN plan_days pd ON pd.id = pm.plan_day_id
           JOIN weekly_plans wp ON wp.id = pd.weekly_plan_id
           WHERE pm.id = ? AND wp.profile_id = ?""",
        (plan_meal_id, profile_id),
    ).fetchone()
    if row is None:
        raise PlanNotFoundError("no such planned meal for this profile")
    return dict(row)


def _current_template_attempt(conn, plan_meal_id: int, slot: str, diet_preference: str) -> int | None:
    """Figures out which template variant (0/1/2) produced the meal's
    current foods, by comparing food-id sets — so swap_meal can start its
    search one variant further along instead of deterministically landing
    back on the exact same template every time."""
    existing_food_ids = {
        r["food_id"] for r in conn.execute(
            "SELECT food_id FROM plan_meal_foods WHERE plan_meal_id = ?", (plan_meal_id,)
        ).fetchall()
    }
    if not existing_food_ids:
        return None
    for attempt in range(MAX_TEMPLATE_ATTEMPTS):
        template = get_template(slot, diet_preference, attempt)
        if template is None:
            continue
        template_food_ids = {
            f["id"] for f in (get_food_by_external_id(ext_id) for ext_id in template) if f is not None
        }
        if template_food_ids == existing_food_ids:
            return attempt
    return None


def swap_meal(plan_meal_id: int, profile_id: str, profile: dict) -> dict:
    """Regenerates ONLY this meal slot, starting the template search one
    variant past whichever produced the current foods — so a swap reliably
    produces something different rather than deterministically re-deriving
    the same template. The rest of the week is untouched."""
    conn = get_connection()
    existing = _get_plan_meal_or_raise(conn, plan_meal_id, profile_id)
    if existing["locked"]:
        raise MealPlanValidationError("cannot swap a locked meal — unlock it first")

    target = get_active_target(profile_id) or compute_nutrition_targets(profile)
    meal_types = determine_meal_slots(profile["meals_per_day"])
    slot = existing["meal_type"]
    slot_index = meal_types.index(slot) if slot in meal_types else 0
    shares = calorie_shares(meal_types)
    target_calories = target["calories"] * shares[slot_index]
    sodium_limit = (target["sodium_mg"] / len(meal_types)) * 1.10

    current_attempt = _current_template_attempt(conn, plan_meal_id, slot, profile["diet_preference"])
    start_attempt = (current_attempt + 1) if current_attempt is not None else 0

    new_meal = _build_meal(slot, profile["diet_preference"], _excluded_terms(profile), target_calories, sodium_limit, start_attempt=start_attempt)
    if new_meal is None:
        raise MealPlanValidationError(f"could not generate a replacement {slot} meeting constraints")

    conn.execute("DELETE FROM plan_meal_foods WHERE plan_meal_id = ?", (plan_meal_id,))
    conn.execute("UPDATE plan_meals SET source = 'generated' WHERE id = ?", (plan_meal_id,))
    for item in new_meal["items"]:
        conn.execute(
            "INSERT INTO plan_meal_foods (plan_meal_id, food_id, serving_id, quantity, grams) VALUES (?, ?, ?, ?, ?)",
            (plan_meal_id, item["food_id"], item["serving_id"], item["quantity"], item["grams"]),
        )
    conn.commit()
    return _load_plan_meal(conn, plan_meal_id)


def set_meal_locked(plan_meal_id: int, profile_id: str, locked: bool) -> dict:
    conn = get_connection()
    _get_plan_meal_or_raise(conn, plan_meal_id, profile_id)
    conn.execute("UPDATE plan_meals SET locked = ? WHERE id = ?", (int(locked), plan_meal_id))
    conn.commit()
    return _load_plan_meal(conn, plan_meal_id)


def mark_meal_source(plan_meal_id: int, profile_id: str, source: str, notes: str | None = None) -> dict:
    if source not in ("restaurant", "leftovers", "generated", "custom"):
        raise MealPlanValidationError(f"invalid source: {source}")
    conn = get_connection()
    _get_plan_meal_or_raise(conn, plan_meal_id, profile_id)
    if source in ("restaurant", "leftovers"):
        # nutrition is unknown/approximate for these — drop any planned items
        # rather than showing stale numbers for food that won't actually be eaten as planned.
        conn.execute("DELETE FROM plan_meal_foods WHERE plan_meal_id = ?", (plan_meal_id,))
    conn.execute("UPDATE plan_meals SET source = ?, notes = ? WHERE id = ?", (source, notes, plan_meal_id))
    conn.commit()
    return _load_plan_meal(conn, plan_meal_id)


def add_custom_meal(plan_day_id: int, profile_id: str, meal_type: str, food_items: list[dict]) -> dict:
    """food_items: [{food_id, serving_id, quantity}]. Deterministic lookup —
    no AI involved in a custom/manual meal entry."""
    conn = get_connection()
    day = conn.execute(
        """SELECT pd.* FROM plan_days pd JOIN weekly_plans wp ON wp.id = pd.weekly_plan_id
           WHERE pd.id = ? AND wp.profile_id = ?""",
        (plan_day_id, profile_id),
    ).fetchone()
    if day is None:
        raise PlanNotFoundError("no such plan day for this profile")

    cur = conn.execute(
        "INSERT INTO plan_meals (plan_day_id, meal_type, locked, source) VALUES (?, ?, 0, 'custom')",
        (plan_day_id, meal_type),
    )
    plan_meal_id = cur.lastrowid
    for item in food_items:
        food = get_food(item["food_id"])
        if food is None:
            raise MealPlanValidationError(f"no such food {item['food_id']}")
        grams = resolve_serving_grams(food, item.get("serving_id"), item["quantity"])
        conn.execute(
            "INSERT INTO plan_meal_foods (plan_meal_id, food_id, serving_id, quantity, grams) VALUES (?, ?, ?, ?, ?)",
            (plan_meal_id, food["id"], item.get("serving_id"), item["quantity"], grams),
        )
    conn.commit()
    return _load_plan_meal(conn, plan_meal_id)


def copy_meal(source_plan_meal_id: int, target_plan_day_id: int, profile_id: str, target_meal_type: str) -> dict:
    conn = get_connection()
    source = _get_plan_meal_or_raise(conn, source_plan_meal_id, profile_id)
    target_day = conn.execute(
        """SELECT pd.* FROM plan_days pd JOIN weekly_plans wp ON wp.id = pd.weekly_plan_id
           WHERE pd.id = ? AND wp.profile_id = ?""",
        (target_plan_day_id, profile_id),
    ).fetchone()
    if target_day is None:
        raise PlanNotFoundError("no such target plan day for this profile")

    source_items = conn.execute(
        "SELECT * FROM plan_meal_foods WHERE plan_meal_id = ?", (source_plan_meal_id,)
    ).fetchall()

    cur = conn.execute(
        "INSERT INTO plan_meals (plan_day_id, meal_type, locked, source) VALUES (?, ?, 0, ?)",
        (target_plan_day_id, target_meal_type, source["source"]),
    )
    new_plan_meal_id = cur.lastrowid
    for item in source_items:
        conn.execute(
            "INSERT INTO plan_meal_foods (plan_meal_id, food_id, serving_id, quantity, grams) VALUES (?, ?, ?, ?, ?)",
            (new_plan_meal_id, item["food_id"], item["serving_id"], item["quantity"], item["grams"]),
        )
    conn.commit()
    return _load_plan_meal(conn, new_plan_meal_id)


def regenerate_day(plan_day_id: int, profile_id: str, profile: dict) -> dict:
    """Regenerates every non-locked meal for this day. Locked meals and
    every OTHER day in the week are left untouched."""
    conn = get_connection()
    day = conn.execute(
        """SELECT pd.* FROM plan_days pd JOIN weekly_plans wp ON wp.id = pd.weekly_plan_id
           WHERE pd.id = ? AND wp.profile_id = ?""",
        (plan_day_id, profile_id),
    ).fetchone()
    if day is None:
        raise PlanNotFoundError("no such plan day for this profile")

    existing_meals = conn.execute(
        "SELECT * FROM plan_meals WHERE plan_day_id = ?", (plan_day_id,)
    ).fetchall()

    for meal_row in existing_meals:
        if meal_row["locked"]:
            continue
        if meal_row["source"] in ("restaurant", "leftovers", "custom"):
            continue  # user-specified content — regenerating a day shouldn't discard it
        swap_meal(meal_row["id"], profile_id, profile)

    return {"day_id": plan_day_id, "day_date": day["day_date"], "meals": [_load_plan_meal(conn, m["id"]) for m in existing_meals]}
