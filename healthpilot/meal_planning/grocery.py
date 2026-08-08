"""Grocery list aggregation: sums grams for every food across a week's
planned meals (skipping restaurant/leftovers slots, which have no foods) and
groups by a fixed category map. Purely arithmetic — no AI involved.
"""
from __future__ import annotations

from nutrition.food_service import get_food

CATEGORY_MAP = {
    "seed:banana": "produce", "seed:apple": "produce", "seed:spinach_cooked": "produce",
    "seed:broccoli_cooked": "produce", "seed:potato_boiled": "produce", "seed:sweet_potato_baked": "produce",
    "seed:avocado": "produce", "seed:orange": "produce", "seed:cucumber": "produce", "seed:tomato": "produce",

    "seed:chicken_breast": "protein", "seed:egg_boiled": "protein", "seed:salmon_cooked": "protein",
    "seed:tofu_firm": "protein", "seed:beef_ground_lean": "protein",

    "seed:milk_lowfat": "dairy", "seed:yogurt_greek_plain": "dairy", "seed:paneer": "dairy",
    "seed:cheddar_cheese": "dairy",

    "seed:rice_white_cooked": "grains", "seed:rice_brown_cooked": "grains", "seed:roti_wheat": "grains",
    "seed:bread_whole_wheat": "grains", "seed:bread_white": "grains", "seed:oats_cooked": "grains",

    "seed:dal_cooked": "pantry", "seed:chickpeas_cooked": "pantry", "seed:almonds": "pantry",
    "seed:peanut_butter": "pantry", "seed:olive_oil": "pantry", "seed:soy_sauce": "pantry",
    "seed:instant_noodles": "pantry", "seed:potato_chips": "pantry",
}

CATEGORIES = ("produce", "protein", "dairy", "grains", "pantry", "frozen", "other")


def categorize(food_external_id: str | None) -> str:
    if food_external_id is None:
        return "other"
    return CATEGORY_MAP.get(food_external_id, "other")


def build_grocery_list(weekly_plan: dict) -> dict:
    """weekly_plan: the dict returned by weekly_planner.get_weekly_plan."""
    totals: dict[tuple[int, str], dict] = {}

    for day in weekly_plan["days"]:
        for meal in day["meals"]:
            for item in meal["items"]:
                key = item["food_id"]
                if key not in totals:
                    totals[key] = {"food_id": key, "food_name": item["food_name"], "grams": 0.0}
                totals[key]["grams"] += item["grams"]

    by_category = {c: [] for c in CATEGORIES}
    for entry in totals.values():
        entry["grams"] = round(entry["grams"], 1)
        food = get_food(entry["food_id"])
        category = categorize(food["external_id"] if food else None)
        by_category[category].append(entry)

    for cat in by_category:
        by_category[cat].sort(key=lambda e: e["food_name"])

    return {"week_start": weekly_plan["week_start"], "by_category": by_category}
