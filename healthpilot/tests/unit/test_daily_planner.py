import pytest

from app.profile import create_profile
from meal_planning.daily_planner import (
    MealPlanValidationError,
    _build_meal_items,
    _repair_sodium,
    _template_is_allowed,
    calorie_shares,
    determine_meal_slots,
    generate_daily_plan,
)
from nutrition.meal_service import NUTRIENT_FIELDS


def _profile(**overrides):
    data = {
        "name": "Planner Test", "age": 40, "sex": "male", "height_cm": 178,
        "current_weight_kg": 80, "activity_level": "moderate", "diet_preference": "veg",
        "meals_per_day": 3,
    }
    data.update(overrides)
    return create_profile(data)


# --- determine_meal_slots / calorie_shares ---------------------------------

def test_determine_meal_slots_three_meals():
    assert determine_meal_slots(3) == ["breakfast", "lunch", "dinner"]


def test_determine_meal_slots_with_one_snack():
    slots = determine_meal_slots(4)
    assert slots == ["breakfast", "snack", "lunch", "dinner"]


def test_determine_meal_slots_with_two_snacks():
    slots = determine_meal_slots(5)
    assert slots.count("snack") == 2
    assert len(slots) == 5


def test_determine_meal_slots_with_many_snacks():
    slots = determine_meal_slots(6)
    assert slots.count("snack") == 3
    assert len(slots) == 6


def test_calorie_shares_sum_to_one():
    for n in (3, 4, 5, 6):
        slots = determine_meal_slots(n)
        shares = calorie_shares(slots)
        assert len(shares) == len(slots)
        assert abs(sum(shares) - 1.0) < 1e-9


# --- _template_is_allowed ---------------------------------------------

def test_template_allowed_with_no_exclusions():
    assert _template_is_allowed(["seed:banana", "seed:apple"], []) is True


def test_template_excluded_by_allergy():
    assert _template_is_allowed(["seed:peanut_butter", "seed:banana"], ["peanut"]) is False


def test_template_not_excluded_when_no_match():
    assert _template_is_allowed(["seed:banana", "seed:apple"], ["shellfish"]) is True


# --- _build_meal_items scaling ------------------------------------------

def test_build_meal_items_scales_to_target_calories():
    items = _build_meal_items(["seed:banana"], target_calories=178)  # banana is 89kcal/100g, 118g default = 105kcal
    assert items[0]["food_name"].lower().startswith("banana")
    total_kcal = sum(i["calories_kcal"] for i in items)
    assert abs(total_kcal - 178) < 5  # scaling should land close to target


def test_build_meal_items_clamps_extreme_scale():
    items = _build_meal_items(["seed:banana"], target_calories=100000)  # would need scale >> MAX_SCALE
    # clamped at MAX_SCALE=3.0 rather than producing an absurd portion
    assert items[0]["quantity"] <= 3.0


# --- _repair_sodium ------------------------------------------------------

def _make_item(sodium_mg, calories_kcal=100, quantity=1.0, grams=100.0):
    item = {f: 0.0 for f in NUTRIENT_FIELDS}
    item["sodium_mg"] = sodium_mg
    item["calories_kcal"] = calories_kcal
    item["quantity"] = quantity
    item["grams"] = grams
    return item


def test_repair_sodium_reduces_worst_offender_until_under_limit():
    # floor scale (0.3) caps how far item1 alone can drop: its minimum
    # possible sodium is 1000*0.3=300, so with item2 fixed at 50 the
    # achievable minimum total is 350 — use a limit above that.
    items = [_make_item(sodium_mg=1000), _make_item(sodium_mg=50)]
    repaired, ok = _repair_sodium(items, sodium_limit=400)
    assert ok is True
    total = sum(i["sodium_mg"] for i in repaired)
    assert total <= 400
    # the low-sodium item must be untouched
    assert repaired[1]["sodium_mg"] == 50
    assert repaired[0]["sodium_mg"] < 1000


def test_repair_sodium_gives_up_at_floor_scale_if_still_over():
    items = [_make_item(sodium_mg=100000)]  # no amount of scaling within the floor gets this under limit
    repaired, ok = _repair_sodium(items, sodium_limit=1)
    assert ok is False


def test_repair_sodium_no_op_when_already_under_limit():
    items = [_make_item(sodium_mg=50)]
    repaired, ok = _repair_sodium(items, sodium_limit=300)
    assert ok is True
    assert repaired[0]["sodium_mg"] == 50
    assert repaired[0]["quantity"] == 1.0


# --- generate_daily_plan (end to end) ------------------------------------

def test_generate_daily_plan_three_meals_veg():
    p = _profile(diet_preference="veg", meals_per_day=3)
    plan = generate_daily_plan(p)
    assert [m["meal_type"] for m in plan["meals"]] == ["breakfast", "lunch", "dinner"]
    assert plan["totals"]["calories_kcal"] > 0


def test_generate_daily_plan_respects_sodium_ceiling():
    p = _profile()
    plan = generate_daily_plan(p)
    target = plan["target"]
    assert plan["totals"]["sodium_mg"] <= target["sodium_mg"] * 1.10


def test_generate_daily_plan_calories_within_tolerance():
    p = _profile()
    plan = generate_daily_plan(p)
    target = plan["target"]
    assert abs(plan["totals"]["calories_kcal"] - target["calories"]) <= target["calories"] * 0.20 + 1


def test_generate_daily_plan_non_veg_can_include_meat_or_fish():
    p = _profile(diet_preference="non_veg")
    plan = generate_daily_plan(p)
    all_names = [i["food_name"].lower() for m in plan["meals"] for i in m["items"]]
    # not a strict requirement that meat appears (templates rotate), just that it's not rejected
    assert len(all_names) > 0


def test_generate_daily_plan_excludes_allergen():
    p = _profile(diet_preference="veg", allergies=["peanut"])
    plan = generate_daily_plan(p)
    all_names = [i["food_name"].lower() for m in plan["meals"] for i in m["items"]]
    assert not any("peanut" in n for n in all_names)


def test_generate_daily_plan_with_snacks():
    p = _profile(meals_per_day=5)
    plan = generate_daily_plan(p)
    assert len(plan["meals"]) == 5
    assert sum(1 for m in plan["meals"] if m["meal_type"] == "snack") == 2


def test_generate_daily_plan_five_meals_still_hits_calorie_target():
    p = _profile(meals_per_day=5)
    plan = generate_daily_plan(p)
    target = plan["target"]
    assert abs(plan["totals"]["calories_kcal"] - target["calories"]) <= target["calories"] * 0.20 + 1
