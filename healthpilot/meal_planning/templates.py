"""Curated meal templates, keyed by slot type and diet preference. Each
template is a list of seed-food external_ids (migrations/003_nutrition_seed_foods.sql)
— dietary correctness (veg vs non_veg) is guaranteed by which foods appear in
which pool, not by a runtime classifier. Multiple variants per (slot, diet)
combination let the planner try an alternate combination when one is
excluded by an allergy/dislike or fails sodium/calorie validation.
"""
from __future__ import annotations

TEMPLATES = {
    "breakfast": {
        "veg": [
            ["oats_cooked", "milk_lowfat", "banana"],
            ["bread_whole_wheat", "peanut_butter", "banana"],
            ["yogurt_greek_plain", "almonds", "apple"],
        ],
        "non_veg": [
            ["egg_boiled", "bread_whole_wheat", "orange"],
            ["oats_cooked", "milk_lowfat", "banana"],
            ["yogurt_greek_plain", "almonds", "apple"],
        ],
    },
    "lunch": {
        "veg": [
            ["rice_white_cooked", "dal_cooked", "spinach_cooked"],
            ["roti_wheat", "chickpeas_cooked", "broccoli_cooked"],
            ["rice_brown_cooked", "tofu_firm", "broccoli_cooked"],
        ],
        "non_veg": [
            ["chicken_breast", "rice_brown_cooked", "broccoli_cooked"],
            ["rice_white_cooked", "dal_cooked", "spinach_cooked"],
            ["salmon_cooked", "sweet_potato_baked", "spinach_cooked"],
        ],
    },
    "dinner": {
        "veg": [
            ["roti_wheat", "chickpeas_cooked", "broccoli_cooked"],
            ["rice_brown_cooked", "tofu_firm", "broccoli_cooked"],
            ["rice_white_cooked", "dal_cooked", "spinach_cooked"],
        ],
        "non_veg": [
            ["salmon_cooked", "sweet_potato_baked", "spinach_cooked"],
            ["chicken_breast", "rice_brown_cooked", "broccoli_cooked"],
            ["rice_white_cooked", "dal_cooked", "spinach_cooked"],
        ],
    },
    "snack": {
        "veg": [
            ["almonds", "apple"],
            ["yogurt_greek_plain", "banana"],
            ["cucumber", "tomato"],
        ],
        "non_veg": [
            ["almonds", "apple"],
            ["yogurt_greek_plain", "banana"],
            ["cucumber", "tomato"],
        ],
    },
}

MAX_TEMPLATE_ATTEMPTS = 3


def get_template(slot_type: str, diet_preference: str, attempt: int) -> list[str] | None:
    """Returns external_ids with the 'seed:' prefix used in the foods table
    (migrations/003_nutrition_seed_foods.sql) — kept bare in TEMPLATES above
    for readability."""
    pool = TEMPLATES.get(slot_type, {}).get(diet_preference)
    if not pool:
        return None
    if attempt >= len(pool):
        return None
    return [f"seed:{name}" for name in pool[attempt]]
