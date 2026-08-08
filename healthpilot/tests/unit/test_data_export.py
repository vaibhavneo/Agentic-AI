import pytest

from app.profile import create_profile
from app.data_export import export_profile_data
from app.medication import create_medication
from exercise.activity_service import log_workout
from nutrition.food_service import default_serving, search_food
from nutrition.meal_service import log_food
from nutrition.targets import recompute_and_store_target
from vitals.bp_service import record_bp
from vitals.sleep_service import record_sleep
from vitals.weight_service import record_weight


def _profile():
    return create_profile(
        {
            "name": "Export Test", "age": 50, "sex": "female", "height_cm": 160,
            "current_weight_kg": 64, "activity_level": "light", "diet_preference": "veg",
        }
    )


def test_export_missing_profile_raises():
    with pytest.raises(ValueError):
        export_profile_data("does-not-exist")


def test_export_includes_everything_logged():
    p = _profile()
    create_medication(p["id"], {"name": "Metformin"})
    recompute_and_store_target(p)
    food = search_food("banana", use_provider=False)[0]
    log_food(p["id"], "breakfast", food["id"], default_serving(food)["id"], 1)
    record_bp(p["id"], systolic_1=118, diastolic_1=76)
    record_weight(p["id"], 64.2)
    record_sleep(p["id"], 7.0)
    log_workout(p["id"], "cardio", "walking", duration_min=20, intensity="light")

    export = export_profile_data(p["id"])
    assert export["profile"]["id"] == p["id"]
    assert len(export["medications"]) == 1
    assert len(export["meals"]) == 1
    assert len(export["nutrition_targets"]) == 1
    assert len(export["bp_readings"]) == 1
    assert len(export["weight_logs"]) == 1
    assert len(export["sleep_logs"]) == 1
    assert len(export["workouts"]) == 1


def test_export_scoped_to_profile():
    a, b = _profile(), _profile()
    record_bp(a["id"], systolic_1=120, diastolic_1=80)
    export_b = export_profile_data(b["id"])
    assert export_b["bp_readings"] == []
