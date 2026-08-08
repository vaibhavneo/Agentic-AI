from app.profile import create_profile
from tools import exercise_tools


def _profile():
    return create_profile(
        {
            "name": "Tool Test", "age": 28, "sex": "male", "height_cm": 180,
            "current_weight_kg": 78, "activity_level": "very_active", "diet_preference": "non_veg",
        }
    )


def test_log_workout_and_today_activity_tool():
    p = _profile()
    exercise_tools.log_workout(p["id"], "cardio", "running", duration_min=25, intensity="vigorous")
    today = exercise_tools.get_today_activity(p["id"])
    assert today["workout_count"] == 1


def test_get_weekly_activity_tool():
    p = _profile()
    exercise_tools.log_workout(p["id"], "cardio", "walking", duration_min=30, intensity="moderate")
    weekly = exercise_tools.get_weekly_activity(p["id"])
    assert weekly["moderate_minutes"] == 30
