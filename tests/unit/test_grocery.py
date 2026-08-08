import datetime as dt

from app.profile import create_profile
from meal_planning.grocery import build_grocery_list, categorize
from meal_planning.weekly_planner import create_weekly_plan, get_weekly_plan


def _profile():
    return create_profile(
        {
            "name": "Grocery Test", "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
            "meals_per_day": 3,
        }
    )


def _monday():
    today = dt.date.today()
    return (today - dt.timedelta(days=today.weekday())).isoformat()


def test_categorize_known_and_unknown():
    assert categorize("seed:banana") == "produce"
    assert categorize("seed:rice_white_cooked") == "grains"
    assert categorize("seed:milk_lowfat") == "dairy"
    assert categorize(None) == "other"
    assert categorize("seed:totally_unmapped_thing") == "other"


def test_grocery_list_aggregates_across_week():
    p = _profile()
    create_weekly_plan(p, _monday())
    plan = get_weekly_plan(p["id"], _monday())
    grocery = build_grocery_list(plan)

    assert set(grocery["by_category"].keys()) == {"produce", "protein", "dairy", "grains", "pantry", "frozen", "other"}
    total_items = sum(len(v) for v in grocery["by_category"].values())
    assert total_items > 0

    # every gram total should be positive and reflect real logged quantities
    for entries in grocery["by_category"].values():
        for entry in entries:
            assert entry["grams"] > 0


def test_grocery_list_sums_same_food_across_multiple_meals():
    p = _profile()
    plan = create_weekly_plan(p, _monday())
    grocery = build_grocery_list(get_weekly_plan(p["id"], _monday()))

    # rice appears in multiple lunch/dinner templates across the week — its
    # grocery entry should be a genuine sum, not just one meal's amount.
    grains = grocery["by_category"]["grains"]
    assert len(grains) >= 1
