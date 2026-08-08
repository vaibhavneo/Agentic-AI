from app.profile import create_profile
from meal_planning.daily_planner import generate_remaining_daily_plan
from nutrition.food_service import default_serving, search_food
from nutrition.meal_service import log_food
from nutrition.targets import recompute_and_store_target


def _profile(**overrides):
    data = {
        "name": "Remaining Plan Test", "age": 45, "sex": "male", "height_cm": 178,
        "current_weight_kg": 85, "activity_level": "moderate", "diet_preference": "veg",
        "meals_per_day": 3,
    }
    data.update(overrides)
    return create_profile(data)


def test_remaining_plan_excludes_already_logged_meal_types():
    p = _profile()
    recompute_and_store_target(p)
    food = search_food("banana", use_provider=False)[0]
    log_food(p["id"], "breakfast", food["id"], default_serving(food)["id"], 1)

    plan = generate_remaining_daily_plan(p)
    meal_types = {m["meal_type"] for m in plan["meals"]}
    assert "breakfast" not in meal_types
    assert meal_types == {"lunch", "dinner"}


def test_remaining_plan_fits_within_leftover_budget():
    p = _profile()
    recompute_and_store_target(p)
    food = search_food("banana", use_provider=False)[0]
    log_food(p["id"], "breakfast", food["id"], default_serving(food)["id"], 1)

    plan = generate_remaining_daily_plan(p)
    assert plan["totals"]["sodium_mg"] <= plan["remaining_target"]["sodium_mg"] * 1.10


def test_remaining_plan_empty_when_everything_already_logged():
    p = _profile(meals_per_day=1)
    recompute_and_store_target(p)
    food = search_food("banana", use_provider=False)[0]
    # meals_per_day=1 -> only slot is "breakfast" (determine_meal_slots)
    log_food(p["id"], "breakfast", food["id"], default_serving(food)["id"], 1)

    plan = generate_remaining_daily_plan(p)
    assert plan["meals"] == []
    assert plan["remaining_target"] is None


def test_remaining_plan_uses_full_day_budget_when_nothing_logged_yet():
    p = _profile()
    recompute_and_store_target(p)
    plan = generate_remaining_daily_plan(p)
    meal_types = {m["meal_type"] for m in plan["meals"]}
    assert meal_types == {"breakfast", "lunch", "dinner"}
    assert plan["remaining_target"]["calories"] == plan["target"]["calories"]
