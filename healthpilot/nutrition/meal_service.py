"""Meals + meal foods, and the deterministic nutrition totals derived from
them. Nothing here ever asks an LLM for a nutrient number — totals are pure
arithmetic over Food rows resolved from nutrition/food_service.py.
"""
from __future__ import annotations

import datetime as dt

from app.validation import validate_date_str
from database.db import get_connection
from nutrition.food_service import (
    FoodValidationError,
    default_serving,
    get_food,
    resolve_serving_grams,
)

VALID_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
NUTRIENT_FIELDS = (
    "calories_kcal", "protein_g", "carbs_g", "fiber_g", "total_fat_g",
    "saturated_fat_g", "sodium_mg", "potassium_mg", "calcium_mg",
    "magnesium_mg", "added_sugar_g",
)


class MealValidationError(ValueError):
    pass


def create_meal(profile_id: str, meal_type: str, meal_date: str | None = None, source: str = "manual", restaurant: bool = False, notes: str | None = None) -> dict:
    if meal_type not in VALID_MEAL_TYPES:
        raise MealValidationError(f"meal_type must be one of {sorted(VALID_MEAL_TYPES)}")
    if meal_date is not None:
        try:
            validate_date_str("meal_date", meal_date)
        except ValueError as e:
            raise MealValidationError(str(e))
    meal_date = meal_date or dt.date.today().isoformat()
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO meals (profile_id, meal_type, meal_date, source, restaurant, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (profile_id, meal_type, meal_date, source, int(restaurant), notes),
    )
    conn.commit()
    return get_meal(cur.lastrowid, profile_id)


def add_meal_food(meal_id: int, profile_id: str, food_id: int, serving_id: int | None, quantity: float) -> dict:
    meal = get_meal(meal_id, profile_id)
    if meal is None:
        raise MealValidationError("no such meal for this profile")
    food = get_food(food_id)
    if food is None:
        raise MealValidationError(f"no such food {food_id}")
    grams = resolve_serving_grams(food, serving_id, quantity)

    conn = get_connection()
    conn.execute(
        "INSERT INTO meal_foods (meal_id, food_id, serving_id, quantity, grams) VALUES (?, ?, ?, ?, ?)",
        (meal_id, food_id, serving_id, quantity, grams),
    )
    conn.commit()
    return get_meal(meal_id, profile_id)


def get_meal(meal_id: int, profile_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM meals WHERE id = ? AND profile_id = ?", (meal_id, profile_id)
    ).fetchone()
    if row is None:
        return None
    items = conn.execute(
        """SELECT mf.id, mf.food_id, mf.serving_id, mf.quantity, mf.grams, f.name AS food_name
           FROM meal_foods mf JOIN foods f ON f.id = mf.food_id
           WHERE mf.meal_id = ?""",
        (meal_id,),
    ).fetchall()
    d = dict(row)
    d["items"] = [dict(i) for i in items]
    return d


def list_meals(profile_id: str, meal_date: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id FROM meals WHERE profile_id = ? AND meal_date = ? ORDER BY logged_at",
        (profile_id, meal_date),
    ).fetchall()
    return [get_meal(r["id"], profile_id) for r in rows]


def delete_meal(meal_id: int, profile_id: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM meals WHERE id = ? AND profile_id = ?", (meal_id, profile_id))
    conn.commit()


def calculate_meal_nutrition(meal_id: int, profile_id: str) -> dict:
    """Deterministic sum over the meal's items, each scaled from its food's
    per-100g values by (grams / 100)."""
    meal = get_meal(meal_id, profile_id)
    if meal is None:
        raise MealValidationError("no such meal for this profile")

    totals = {f: 0.0 for f in NUTRIENT_FIELDS}
    for item in meal["items"]:
        food = get_food(item["food_id"])
        scale = item["grams"] / 100.0
        for f in NUTRIENT_FIELDS:
            totals[f] += food[f] * scale

    totals = {k: round(v, 2) for k, v in totals.items()}
    return {"meal_id": meal_id, "meal_type": meal["meal_type"], **totals}


def log_food(profile_id: str, meal_type: str, food_id: int, serving_id: int | None, quantity: float, meal_date: str | None = None, restaurant: bool = False, source: str = "manual") -> dict:
    """Convenience path used by quick-add UI and the NL logging pipeline:
    creates (or reuses today's) meal of the given type and appends one food
    item to it, returning the updated meal with computed nutrition."""
    meal_date = meal_date or dt.date.today().isoformat()
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM meals WHERE profile_id = ? AND meal_type = ? AND meal_date = ? AND source != 'plan' ORDER BY id LIMIT 1",
        (profile_id, meal_type, meal_date),
    ).fetchone()
    if existing:
        meal_id = existing["id"]
    else:
        meal = create_meal(profile_id, meal_type, meal_date, source=source, restaurant=restaurant)
        meal_id = meal["id"]

    meal = add_meal_food(meal_id, profile_id, food_id, serving_id, quantity)
    nutrition = calculate_meal_nutrition(meal_id, profile_id)
    return {**meal, "nutrition": nutrition}
