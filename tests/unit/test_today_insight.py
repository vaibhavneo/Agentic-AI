import datetime as dt

from app.profile import create_profile
from insights.today_insight import get_today_insight
from nutrition.food_service import default_serving, search_food
from nutrition.meal_service import log_food
from nutrition.targets import recompute_and_store_target
from vitals.bp_service import record_bp


def _profile():
    return create_profile(
        {
            "name": "Insight Test", "age": 37, "sex": "female", "height_cm": 168,
            "current_weight_kg": 66, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_no_data_gives_honest_fallback():
    p = _profile()
    insight = get_today_insight(p["id"])
    assert insight["source"] == "none"
    assert "not enough data" in insight["text"].lower()


def test_rising_bp_trend_surfaced_when_present():
    p = _profile()
    today = dt.date.today()
    for i, systolic in enumerate([112, 114, 130, 135]):
        day = today - dt.timedelta(days=9 - i * 2)
        record_bp(p["id"], systolic_1=systolic, diastolic_1=76, reading_date=day.isoformat())
    insight = get_today_insight(p["id"])
    assert insight["source"] == "bp_trend"
    assert "rising" in insight["text"].lower()


def test_sodium_remaining_surfaced_when_no_trend_data():
    p = _profile()
    recompute_and_store_target(p)
    food = search_food("banana", use_provider=False)[0]
    log_food(p["id"], "breakfast", food["id"], default_serving(food)["id"], 1)
    insight = get_today_insight(p["id"])
    assert insight["source"] == "today_nutrition"
    assert "sodium" in insight["text"].lower()
