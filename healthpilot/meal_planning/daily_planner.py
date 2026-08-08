"""Deterministic daily meal plan generator + validator.

An AI agent (M6's Nutrition Planner) may eventually propose which template
variant or substitute food to try first, but the arithmetic that assembles
portions and the pass/fail check against sodium/calorie constraints is 100%
deterministic and lives here — a plan that fails validation after all repair
attempts is rejected outright, never returned to the caller.
"""
from __future__ import annotations

import datetime as dt

from nutrition.daily_service import calculate_daily_nutrition
from nutrition.food_service import default_serving, get_food_by_external_id
from nutrition.meal_service import NUTRIENT_FIELDS, list_meals
from nutrition.targets import compute_nutrition_targets, get_active_target
from meal_planning.templates import MAX_TEMPLATE_ATTEMPTS, get_template

CALORIE_TOLERANCE = 0.20        # accept a day within +/-20% of the calorie target
SODIUM_TOLERANCE = 1.10         # accept a day up to 10% over the sodium target after repair
MIN_SCALE = 0.4
MAX_SCALE = 3.0
SODIUM_REPAIR_ITERATIONS = 5
SODIUM_REPAIR_FACTOR = 0.8
SODIUM_REPAIR_FLOOR_SCALE = 0.3


class MealPlanValidationError(ValueError):
    pass


def determine_meal_slots(meals_per_day: int) -> list[str]:
    main = ["breakfast", "lunch", "dinner"]
    if meals_per_day <= 3:
        return main[: max(1, meals_per_day)]
    snack_count = meals_per_day - 3
    slots = ["breakfast", "lunch", "dinner"]
    # interleave snacks after breakfast/lunch for a more natural running order
    if snack_count >= 1:
        slots = ["breakfast", "snack", "lunch", "dinner"]
    if snack_count >= 2:
        slots = ["breakfast", "snack", "lunch", "snack", "dinner"]
    return slots[: 3 + min(snack_count, 2)] if snack_count <= 2 else slots + ["snack"] * (snack_count - 2)


def calorie_shares(meal_types: list[str]) -> list[float]:
    """Returns a list of fractions aligned index-for-index with meal_types
    (a plain dict can't hold this — 'snack' can repeat). Snacks split a
    fixed pool off the top; the three main meals split what's left by their
    relative weights."""
    snack_count = meal_types.count("snack")
    snack_share_total = min(0.10 * snack_count, 0.25)
    remaining = 1.0 - snack_share_total
    main_weights = {"breakfast": 0.30, "lunch": 0.40, "dinner": 0.30}
    main_slots = [m for m in meal_types if m != "snack"]
    main_weight_sum = sum(main_weights[m] for m in main_slots) or 1.0

    shares = []
    for m in meal_types:
        if m == "snack":
            shares.append(snack_share_total / snack_count if snack_count else 0)
        else:
            shares.append(remaining * (main_weights[m] / main_weight_sum))
    return shares


def suggested_meal_times(meal_types: list[str], wake_time: str | None, bed_time: str | None) -> list[str | None]:
    """Spaces meal slots proportionally across the user's wake-to-bed window,
    using each slot's calorie share as its width — breakfast lands soon
    after wake_time, dinner lands before bed_time, snacks fall between.
    Informational only (never blocks/affects plan generation or validation);
    returns None for every slot when wake_time/bed_time aren't both set."""
    if not wake_time or not bed_time:
        return [None] * len(meal_types)

    def _to_minutes(hhmm: str) -> int:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    wake_min = _to_minutes(wake_time)
    bed_min = _to_minutes(bed_time)
    if bed_min <= wake_min:
        bed_min += 24 * 60  # bedtime past midnight

    awake_window = bed_min - wake_min
    shares = calorie_shares(meal_types)
    cumulative = 0.0
    times = []
    for share in shares:
        midpoint_fraction = cumulative + share / 2
        cumulative += share
        minute = int(wake_min + midpoint_fraction * awake_window) % (24 * 60)
        times.append(f"{minute // 60:02d}:{minute % 60:02d}")
    return times


def _excluded_terms(profile: dict) -> list[str]:
    terms = []
    for field in ("allergies", "intolerances", "disliked_foods"):
        terms.extend(t.lower().strip() for t in profile.get(field, []) if t.strip())
    return terms


def _template_is_allowed(external_ids: list[str], excluded_terms: list[str]) -> bool:
    if not excluded_terms:
        return True
    for ext_id in external_ids:
        food = get_food_by_external_id(ext_id)
        if food is None:
            return False
        name_lower = food["name"].lower()
        if any(term in name_lower for term in excluded_terms):
            return False
    return True


def _build_meal_items(external_ids: list[str], target_calories: float) -> list[dict]:
    foods = [get_food_by_external_id(ext_id) for ext_id in external_ids]
    if any(f is None for f in foods):
        raise MealPlanValidationError(f"template references unknown food(s): {external_ids}")

    servings = [default_serving(f) for f in foods]
    base_calories = sum(f["calories_kcal"] * s["grams"] / 100 for f, s in zip(foods, servings))
    scale = target_calories / base_calories if base_calories > 0 else 1.0
    scale = max(MIN_SCALE, min(MAX_SCALE, scale))

    items = []
    for food, serving in zip(foods, servings):
        grams = serving["grams"] * scale
        items.append({
            "food_id": food["id"],
            "food_name": food["name"],
            "serving_id": serving["id"],
            "serving_description": serving["description"],
            "quantity": round(scale, 2),
            "grams": round(grams, 1),
            **{f: round(food[f] * grams / 100, 2) for f in NUTRIENT_FIELDS},
        })
    return items


def _meal_totals(items: list[dict]) -> dict:
    return {f: round(sum(i[f] for i in items), 2) for f in NUTRIENT_FIELDS}


def _repair_sodium(items: list[dict], sodium_limit: float) -> tuple[list[dict], bool]:
    items = [dict(i) for i in items]
    for _ in range(SODIUM_REPAIR_ITERATIONS):
        total_sodium = sum(i["sodium_mg"] for i in items)
        if total_sodium <= sodium_limit:
            return items, True
        worst = max(items, key=lambda i: i["sodium_mg"])
        if worst["quantity"] <= SODIUM_REPAIR_FLOOR_SCALE:
            break
        new_quantity = max(SODIUM_REPAIR_FLOOR_SCALE, worst["quantity"] * SODIUM_REPAIR_FACTOR)
        factor = new_quantity / worst["quantity"]
        worst["quantity"] = round(new_quantity, 2)
        worst["grams"] = round(worst["grams"] * factor, 1)
        for f in NUTRIENT_FIELDS:
            worst[f] = round(worst[f] * factor, 2)
    total_sodium = sum(i["sodium_mg"] for i in items)
    return items, total_sodium <= sodium_limit


def _build_meal(slot: str, diet_preference: str, excluded_terms: list[str], target_calories: float, sodium_limit: float, start_attempt: int = 0) -> dict | None:
    """start_attempt rotates which template variant is tried first — used by
    swap_meal so 'swap' actually produces something different instead of
    deterministically re-deriving the same first-successful template every
    time. generate_daily_plan/create_weekly_plan always call with the
    default 0 so a fresh plan stays fully reproducible."""
    for i in range(MAX_TEMPLATE_ATTEMPTS):
        attempt = (start_attempt + i) % MAX_TEMPLATE_ATTEMPTS
        template = get_template(slot, diet_preference, attempt)
        if template is None or not _template_is_allowed(template, excluded_terms):
            continue
        items = _build_meal_items(template, target_calories)
        totals = _meal_totals(items)
        if totals["sodium_mg"] > sodium_limit:
            items, ok = _repair_sodium(items, sodium_limit)
            if not ok:
                continue
            totals = _meal_totals(items)
        return {"meal_type": slot, "items": items, "totals": totals}
    return None


def generate_daily_plan(profile: dict, target: dict | None = None) -> dict:
    """Raises MealPlanValidationError if no combination of templates can
    satisfy the profile's constraints — the caller must not display a
    partially-broken plan."""
    target = target or get_active_target(profile["id"]) or compute_nutrition_targets(profile)
    meal_types = determine_meal_slots(profile["meals_per_day"])
    shares = calorie_shares(meal_types)
    excluded_terms = _excluded_terms(profile)
    sodium_limit_per_meal = target["sodium_mg"] / len(meal_types)

    for day_attempt in range(MAX_TEMPLATE_ATTEMPTS):
        meals = []
        failed = False
        for i, slot in enumerate(meal_types):
            target_calories = target["calories"] * shares[i]
            meal = _build_meal(slot, profile["diet_preference"], excluded_terms, target_calories, sodium_limit_per_meal * SODIUM_TOLERANCE)
            if meal is None:
                failed = True
                break
            meals.append(meal)
        if failed:
            continue

        day_totals = {f: round(sum(m["totals"][f] for m in meals), 2) for f in NUTRIENT_FIELDS}
        calorie_ok = abs(day_totals["calories_kcal"] - target["calories"]) <= target["calories"] * CALORIE_TOLERANCE
        sodium_ok = day_totals["sodium_mg"] <= target["sodium_mg"] * SODIUM_TOLERANCE
        if calorie_ok and sodium_ok:
            times = suggested_meal_times(meal_types, profile.get("wake_time"), profile.get("bed_time"))
            for m, t in zip(meals, times):
                m["suggested_time"] = t
            return {"meals": meals, "totals": day_totals, "target": target}

    raise MealPlanValidationError(
        "Could not generate a daily plan meeting this profile's calorie/sodium constraints "
        "from the available food templates — rejecting rather than showing an invalid plan."
    )


def generate_remaining_daily_plan(profile: dict, target: dict | None = None) -> dict:
    """Plans only today's not-yet-logged meal slots, sized against what's
    LEFT of the day's calorie/sodium budget after what's already been eaten
    — not the full day's target. Still deterministic validate/repair/reject,
    scoped to the remaining slots only."""
    target = target or get_active_target(profile["id"]) or compute_nutrition_targets(profile)
    today = dt.date.today().isoformat()
    logged_meal_types = {m["meal_type"] for m in list_meals(profile["id"], today)}
    all_slots = determine_meal_slots(profile["meals_per_day"])
    remaining_slots = [s for s in all_slots if s not in logged_meal_types]

    if not remaining_slots:
        empty_totals = {f: 0.0 for f in NUTRIENT_FIELDS}
        return {"meals": [], "totals": empty_totals, "target": target, "remaining_target": None}

    consumed = calculate_daily_nutrition(profile["id"], today)["totals"]
    remaining_target = {
        "calories": max(200, target["calories"] - consumed["calories_kcal"]),
        "sodium_mg": max(100, target["sodium_mg"] - consumed["sodium_mg"]),
    }

    excluded_terms = _excluded_terms(profile)
    shares = calorie_shares(remaining_slots)
    sodium_limit_per_meal = remaining_target["sodium_mg"] / len(remaining_slots)

    for _attempt in range(MAX_TEMPLATE_ATTEMPTS):
        meals = []
        failed = False
        for i, slot in enumerate(remaining_slots):
            target_calories = remaining_target["calories"] * shares[i]
            meal = _build_meal(slot, profile["diet_preference"], excluded_terms, target_calories, sodium_limit_per_meal * SODIUM_TOLERANCE)
            if meal is None:
                failed = True
                break
            meals.append(meal)
        if failed:
            continue

        totals = {f: round(sum(m["totals"][f] for m in meals), 2) for f in NUTRIENT_FIELDS}
        if totals["sodium_mg"] <= remaining_target["sodium_mg"] * SODIUM_TOLERANCE:
            times = suggested_meal_times(remaining_slots, profile.get("wake_time"), profile.get("bed_time"))
            for m, t in zip(meals, times):
                m["suggested_time"] = t
            return {"meals": meals, "totals": totals, "target": target, "remaining_target": remaining_target}

    raise MealPlanValidationError(
        "Could not generate remaining meals that fit today's leftover sodium/calorie budget — "
        "rejecting rather than showing an invalid plan."
    )
