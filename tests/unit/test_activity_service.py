import datetime as dt

import pytest

from app.profile import create_profile
from exercise.activity_service import (
    ActivityValidationError,
    conservative_dietary_credit,
    delete_workout,
    get_today_activity,
    get_weekly_activity,
    log_workout,
)


def _profile():
    return create_profile(
        {
            "name": "Test", "age": 30, "sex": "male", "height_cm": 178,
            "current_weight_kg": 75, "activity_level": "active", "diet_preference": "veg",
        }
    )


def test_log_cardio_requires_intensity():
    p = _profile()
    with pytest.raises(ActivityValidationError):
        log_workout(p["id"], "cardio", "running", duration_min=30)


def test_log_cardio_success():
    p = _profile()
    w = log_workout(p["id"], "cardio", "running", duration_min=30, intensity="vigorous", distance_km=5)
    assert w["workout_type"] == "cardio"
    assert w["intensity"] == "vigorous"


def test_log_strength_with_sets():
    p = _profile()
    w = log_workout(
        p["id"], "strength", "strength_training", duration_min=45,
        strength_sets=[
            {"exercise_name": "Squat", "reps": 8, "weight_kg": 60},
            {"exercise_name": "Squat", "reps": 8, "weight_kg": 62.5},
        ],
    )
    assert len(w["sets"]) == 2
    assert w["sets"][0]["exercise_name"] == "Squat"


def test_invalid_workout_type_rejected():
    p = _profile()
    with pytest.raises(ActivityValidationError):
        log_workout(p["id"], "yoga", "yoga session")


def test_out_of_range_duration_rejected():
    p = _profile()
    with pytest.raises(ActivityValidationError):
        log_workout(p["id"], "cardio", "running", intensity="moderate", duration_min=99999)


def test_strength_set_missing_exercise_name_rejected():
    p = _profile()
    with pytest.raises(ActivityValidationError):
        log_workout(p["id"], "strength", "gym", strength_sets=[{"reps": 8}])


def test_conservative_dietary_credit_is_discounted():
    assert conservative_dietary_credit(400) == 300.0
    assert conservative_dietary_credit(None) is None


def test_delete_workout_removes_it():
    p = _profile()
    w = log_workout(p["id"], "cardio", "walking", duration_min=20, intensity="light")
    delete_workout(w["id"], p["id"])
    today = get_today_activity(p["id"])
    assert today["workout_count"] == 0


def test_weekly_rollup_separates_moderate_and_vigorous_minutes():
    p = _profile()
    log_workout(p["id"], "cardio", "walking", duration_min=30, intensity="moderate")
    log_workout(p["id"], "cardio", "running", duration_min=20, intensity="vigorous")
    weekly = get_weekly_activity(p["id"])
    assert weekly["moderate_minutes"] == 30
    assert weekly["vigorous_minutes"] == 20
    assert weekly["weighted_aerobic_minutes"] == 30 + 2 * 20


def test_weekly_rollup_counts_distinct_strength_days():
    p = _profile()
    today = dt.date.today().isoformat()
    log_workout(p["id"], "strength", "gym", duration_min=45, workout_date=today)
    log_workout(p["id"], "strength", "gym", duration_min=45, workout_date=today)  # same day, second session
    weekly = get_weekly_activity(p["id"])
    assert weekly["strength_days"] == 1


def test_weekly_rollup_sums_distance_and_steps():
    p = _profile()
    log_workout(p["id"], "cardio", "running", duration_min=25, intensity="vigorous", distance_km=5, steps=6000)
    log_workout(p["id"], "cardio", "walking", duration_min=15, intensity="light", distance_km=1.2, steps=1800)
    weekly = get_weekly_activity(p["id"])
    assert weekly["total_distance_km"] == 6.2
    assert weekly["total_steps"] == 7800


def test_weekly_rollup_credits_wearable_calories_conservatively():
    p = _profile()
    log_workout(p["id"], "cardio", "running", duration_min=30, intensity="vigorous", wearable_calories=400)
    weekly = get_weekly_activity(p["id"])
    assert weekly["total_wearable_calories"] == 400
    assert weekly["conservative_dietary_credit"] == 300.0  # never 1:1
