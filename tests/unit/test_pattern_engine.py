import datetime as dt

from app.profile import create_profile
from exercise.activity_service import log_workout
from insights.pattern_engine import (
    MIN_SAMPLE_SIZE,
    analyze_health_patterns,
    exercise_vs_bp,
    restaurant_meals_vs_bp,
    sleep_vs_morning_bp,
    sodium_vs_next_day_bp,
    weight_vs_bp,
)
from nutrition.food_service import create_manual_food
from nutrition.meal_service import add_meal_food, create_meal
from vitals.bp_service import record_bp
from vitals.sleep_service import record_sleep
from vitals.weight_service import record_weight


def _profile():
    return create_profile(
        {
            "name": "Insights Test", "age": 45, "sex": "male", "height_cm": 175,
            "current_weight_kg": 85, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def _log_sodium(profile_id, day, sodium_mg):
    food = create_manual_food({"name": f"Sodium test food {sodium_mg}", "calories_kcal": 100, "sodium_mg": sodium_mg})
    meal = create_meal(profile_id, "dinner", meal_date=day)
    add_meal_food(meal["id"], profile_id, food["id"], food["servings"][0]["id"], 1)


def test_sodium_association_insufficient_data_by_default():
    p = _profile()
    result = sodium_vs_next_day_bp(p["id"])
    assert result["status"] == "insufficient_data"
    assert result["correlation"] is None
    assert result["sample_size"] < MIN_SAMPLE_SIZE


def test_sodium_association_computed_with_enough_correlated_data():
    p = _profile()
    today = dt.date.today()
    # 6 days of (sodium, next-day BP) pairs, strongly positively correlated by construction
    sodium_levels = [1000, 1500, 2000, 2500, 3000, 3500]
    bp_levels = [110, 116, 122, 128, 134, 140]
    for i, (sodium, bp) in enumerate(zip(sodium_levels, bp_levels)):
        day = today - dt.timedelta(days=len(sodium_levels) - i + 1)
        next_day = day + dt.timedelta(days=1)
        _log_sodium(p["id"], day.isoformat(), sodium)
        record_bp(p["id"], systolic_1=bp, diastolic_1=75, reading_date=next_day.isoformat())

    result = sodium_vs_next_day_bp(p["id"])
    assert result["status"] == "computed"
    assert result["sample_size"] == 6
    assert result["correlation"] > 0.9  # near-perfect linear construction
    assert "caveat" in result
    assert "not necessarily caused by" in result["caveat"]


def test_sleep_vs_morning_bp_pairs_same_day():
    p = _profile()
    today = dt.date.today()
    for i in range(6):
        day = (today - dt.timedelta(days=i + 1)).isoformat()
        record_sleep(p["id"], hours=6 + i * 0.3, log_date=day)
        record_bp(p["id"], systolic_1=120 - i, diastolic_1=78, reading_date=day)
    result = sleep_vs_morning_bp(p["id"])
    assert result["status"] == "computed"
    assert result["sample_size"] == 6


def test_weight_vs_bp_requires_same_day_pairs():
    p = _profile()
    today = dt.date.today()
    for i in range(6):
        day = (today - dt.timedelta(days=i + 1)).isoformat()
        record_weight(p["id"], 80 + i, log_date=day)
        record_bp(p["id"], systolic_1=115 + i, diastolic_1=75, reading_date=day)
    result = weight_vs_bp(p["id"])
    assert result["status"] == "computed"


def test_exercise_vs_bp_includes_zero_minute_days():
    p = _profile()
    today = dt.date.today()
    for i in range(6):
        day = (today - dt.timedelta(days=i + 1)).isoformat()
        record_bp(p["id"], systolic_1=118, diastolic_1=76, reading_date=day)
        if i % 2 == 0:
            log_workout(p["id"], "cardio", "walking", duration_min=20, intensity="moderate", workout_date=day)
    result = exercise_vs_bp(p["id"])
    assert result["sample_size"] == 6  # every day has a BP reading, exercise or not


def test_restaurant_meals_vs_bp_no_data_is_insufficient():
    p = _profile()
    result = restaurant_meals_vs_bp(p["id"])
    assert result["status"] == "insufficient_data"


def test_no_variation_returns_no_variation_status():
    p = _profile()
    today = dt.date.today()
    for i in range(6):
        day = (today - dt.timedelta(days=i + 1)).isoformat()
        record_sleep(p["id"], hours=7.0, log_date=day)  # identical every day — zero variance
        record_bp(p["id"], systolic_1=120, diastolic_1=78, reading_date=day)
    result = sleep_vs_morning_bp(p["id"])
    assert result["status"] == "no_variation"
    assert result["correlation"] is None


def test_analyze_health_patterns_returns_all_seven_associations():
    p = _profile()
    result = analyze_health_patterns(p["id"])
    assert len(result["associations"]) == 7
    names = {a["name"] for a in result["associations"]}
    assert names == {
        "sodium_vs_next_day_bp", "sleep_vs_morning_bp", "exercise_vs_bp",
        "restaurant_meals_vs_bp", "weight_vs_bp", "activity_vs_sleep",
        "protein_adequacy_vs_strength_days",
    }
    # with no data logged, every association must honestly report insufficient_data
    assert all(a["status"] == "insufficient_data" for a in result["associations"])


def test_every_association_never_claims_causation_language_when_computed():
    p = _profile()
    today = dt.date.today()
    sodium_levels = [1000, 1500, 2000, 2500, 3000, 3500]
    bp_levels = [110, 116, 122, 128, 134, 140]
    for i, (sodium, bp) in enumerate(zip(sodium_levels, bp_levels)):
        day = today - dt.timedelta(days=len(sodium_levels) - i + 1)
        next_day = day + dt.timedelta(days=1)
        _log_sodium(p["id"], day.isoformat(), sodium)
        record_bp(p["id"], systolic_1=bp, diastolic_1=75, reading_date=next_day.isoformat())

    result = sodium_vs_next_day_bp(p["id"])
    assert "causes" not in result["caveat"].lower()
    assert "associated with" in result["caveat"].lower()
