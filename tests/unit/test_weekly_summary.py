import datetime as dt

from app.profile import create_profile
from insights.weekly_summary import get_weekly_summary
from nutrition.food_service import default_serving, search_food
from nutrition.meal_service import log_food


def _profile():
    return create_profile(
        {
            "name": "Weekly Summary Test", "age": 29, "sex": "male", "height_cm": 180,
            "current_weight_kg": 76, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_weekly_summary_with_no_data():
    p = _profile()
    summary = get_weekly_summary(p["id"])
    assert summary["avg_sodium_mg"] is None
    assert summary["calorie_change_vs_last_week"] is None
    assert summary["bp_average_7day"]["sample_size"] == 0


def test_weekly_summary_computes_averages_from_logged_meals():
    p = _profile()
    food = search_food("rice", use_provider=False)[0]
    serving = default_serving(food)
    today = dt.date.today().isoformat()
    log_food(p["id"], "lunch", food["id"], serving["id"], 1, meal_date=today)

    summary = get_weekly_summary(p["id"])
    assert summary["avg_sodium_mg"] is not None
    assert summary["avg_calories_kcal"] is not None
