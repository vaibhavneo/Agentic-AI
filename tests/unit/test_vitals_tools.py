from app.profile import create_profile
from tools import vitals_tools


def _profile():
    return create_profile(
        {
            "name": "Tool Test", "age": 50, "sex": "female", "height_cm": 168,
            "current_weight_kg": 65, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_record_bp_tool_matches_service():
    p = _profile()
    reading = vitals_tools.record_bp(p["id"], 130, 85)
    assert reading["category"] == "stage_1"


def test_bp_history_and_average_tools():
    p = _profile()
    vitals_tools.record_bp(p["id"], 120, 80)
    vitals_tools.record_bp(p["id"], 124, 82)
    assert len(vitals_tools.get_bp_history(p["id"])) == 2
    avg = vitals_tools.calculate_bp_average(p["id"])
    assert avg["sample_size"] == 2


def test_weight_and_sleep_tools():
    p = _profile()
    vitals_tools.record_weight(p["id"], 65.5)
    assert len(vitals_tools.get_weight_history(p["id"])) == 1
    vitals_tools.record_sleep(p["id"], 7)
    assert len(vitals_tools.get_sleep_history(p["id"])) == 1
