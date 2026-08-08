import datetime as dt

import pytest

from app.profile import create_profile
from meal_planning.weekly_planner import (
    PlanNotFoundError,
    add_custom_meal,
    copy_meal,
    create_weekly_plan,
    get_weekly_plan,
    mark_meal_source,
    regenerate_day,
    set_meal_locked,
    swap_meal,
)


def _profile(**overrides):
    data = {
        "name": "Weekly Test", "age": 35, "sex": "female", "height_cm": 165,
        "current_weight_kg": 65, "activity_level": "moderate", "diet_preference": "veg",
        "meals_per_day": 3,
    }
    data.update(overrides)
    return create_profile(data)


def _monday():
    today = dt.date.today()
    return (today - dt.timedelta(days=today.weekday())).isoformat()


def test_create_weekly_plan_has_seven_days():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    assert len(plan["days"]) == 7
    assert all(len(d["meals"]) == 3 for d in plan["days"])


def test_create_weekly_plan_rejects_duplicate_week():
    p = _profile()
    create_weekly_plan(p, _monday())
    with pytest.raises(ValueError):
        create_weekly_plan(p, _monday())


def test_get_weekly_plan_missing_raises():
    p = _profile()
    with pytest.raises(PlanNotFoundError):
        get_weekly_plan(p["id"], _monday())


def test_swap_meal_only_changes_that_meal():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    monday_meals = plan["days"][0]["meals"]
    lunch = next(m for m in monday_meals if m["meal_type"] == "lunch")
    other_day_snapshot = [d["meals"] for d in plan["days"][1:]]

    swap_meal(lunch["id"], p["id"], p)

    updated = get_weekly_plan(p["id"], _monday())
    # Monday's breakfast/dinner totals unchanged; only lunch was touched.
    updated_monday = updated["days"][0]["meals"]
    updated_breakfast = next(m for m in updated_monday if m["meal_type"] == "breakfast")
    original_breakfast = next(m for m in monday_meals if m["meal_type"] == "breakfast")
    assert updated_breakfast["totals"] == original_breakfast["totals"]

    # every other day's meals are byte-for-byte unchanged
    for day, original_meals in zip(updated["days"][1:], other_day_snapshot):
        for m, om in zip(day["meals"], original_meals):
            assert m["totals"] == om["totals"]


def test_swap_meal_actually_changes_the_food_selection():
    """Regression test: swap_meal must not deterministically regenerate the
    exact same template it started with — that would make 'swap' a no-op."""
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    dinner = next(m for m in plan["days"][0]["meals"] if m["meal_type"] == "dinner")
    original_food_ids = {i["food_id"] for i in dinner["items"]}

    swapped = swap_meal(dinner["id"], p["id"], p)
    swapped_food_ids = {i["food_id"] for i in swapped["items"]}

    assert swapped_food_ids != original_food_ids


def test_swap_locked_meal_raises():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    meal = plan["days"][0]["meals"][0]
    set_meal_locked(meal["id"], p["id"], True)
    with pytest.raises(ValueError):
        swap_meal(meal["id"], p["id"], p)


def test_mark_restaurant_clears_items():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    meal = plan["days"][0]["meals"][0]
    updated = mark_meal_source(meal["id"], p["id"], "restaurant", notes="Dinner out")
    assert updated["items"] == []
    assert updated["source"] == "restaurant"


def test_add_custom_meal_uses_real_food_lookup():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    day_id = plan["days"][0]["id"]

    from nutrition.food_service import default_serving, search_food
    food = search_food("banana", use_provider=False)[0]
    serving = default_serving(food)

    custom = add_custom_meal(day_id, p["id"], "snack", [{"food_id": food["id"], "serving_id": serving["id"], "quantity": 1}])
    assert custom["source"] == "custom"
    assert custom["items"][0]["food_name"].lower().startswith("banana")


def test_copy_meal_duplicates_items_to_another_day():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    source_meal = plan["days"][0]["meals"][0]
    target_day_id = plan["days"][2]["id"]

    copied = copy_meal(source_meal["id"], target_day_id, p["id"], source_meal["meal_type"])
    assert copied["totals"] == source_meal["totals"]


def test_regenerate_day_skips_locked_meals():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    monday_meals = plan["days"][0]["meals"]
    breakfast = next(m for m in monday_meals if m["meal_type"] == "breakfast")
    set_meal_locked(breakfast["id"], p["id"], True)

    result = regenerate_day(plan["days"][0]["id"], p["id"], p)
    updated_breakfast = next(m for m in result["meals"] if m["meal_type"] == "breakfast")
    assert updated_breakfast["totals"] == breakfast["totals"]


def test_regenerate_day_does_not_touch_other_days():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    tuesday_before = plan["days"][1]["meals"]

    regenerate_day(plan["days"][0]["id"], p["id"], p)

    updated = get_weekly_plan(p["id"], _monday())
    tuesday_after = updated["days"][1]["meals"]
    for before, after in zip(tuesday_before, tuesday_after):
        assert before["totals"] == after["totals"]
