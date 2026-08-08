import datetime as dt

from app.profile import create_profile
from tools import meal_planning_tools


def _profile():
    return create_profile(
        {
            "name": "Tool Test", "age": 32, "sex": "male", "height_cm": 176,
            "current_weight_kg": 74, "activity_level": "moderate", "diet_preference": "veg",
            "meals_per_day": 3,
        }
    )


def _monday():
    today = dt.date.today()
    return (today - dt.timedelta(days=today.weekday())).isoformat()


def test_generate_daily_plan_tool():
    p = _profile()
    plan = meal_planning_tools.generate_daily_plan(p["id"])
    assert len(plan["meals"]) == 3


def test_generate_weekly_plan_and_grocery_list_tools():
    p = _profile()
    week_start = _monday()
    plan = meal_planning_tools.generate_weekly_plan(p["id"], week_start)
    assert len(plan["days"]) == 7

    grocery = meal_planning_tools.build_grocery_list(p["id"], week_start)
    assert "by_category" in grocery


def test_swap_meal_tool():
    p = _profile()
    week_start = _monday()
    plan = meal_planning_tools.generate_weekly_plan(p["id"], week_start)
    meal_id = plan["days"][0]["meals"][0]["id"]
    swapped = meal_planning_tools.swap_meal(meal_id, p["id"])
    assert swapped["id"] == meal_id
