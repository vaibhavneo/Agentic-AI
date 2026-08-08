from app.profile import create_profile
from agents.fallback_coach import answer_without_ai
from nutrition.targets import recompute_and_store_target


def _profile():
    return create_profile(
        {
            "name": "Fallback Test", "age": 38, "sex": "male", "height_cm": 180,
            "current_weight_kg": 82, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_protein_question_uses_real_target_data():
    p = _profile()
    recompute_and_store_target(p)
    result = answer_without_ai(p["id"], "How much protein do I have left today?")
    assert result["ai_used"] is False
    assert len(result["data_used"]) == 1
    assert result["data_used"][0]["tool"] == "get_remaining_nutrition_targets"
    assert "g of protein" in result["answer"]


def test_protein_question_without_target_set_is_honest():
    p = _profile()
    result = answer_without_ai(p["id"], "protein remaining?")
    assert "no nutrition target" in result["answer"].lower() or "compute one" in result["answer"].lower()


def test_bp_question_with_no_readings_is_honest():
    p = _profile()
    result = answer_without_ai(p["id"], "what's my blood pressure trend")
    assert "no bp readings" in result["answer"].lower()


def test_activity_question_uses_weekly_tool():
    p = _profile()
    result = answer_without_ai(p["id"], "how was my workout this week")
    assert result["data_used"][0]["tool"] == "get_weekly_activity"


def test_pattern_question_reports_insufficient_data_honestly():
    p = _profile()
    result = answer_without_ai(p["id"], "is there a pattern between my sleep and BP")
    assert "not enough data" in result["answer"].lower()


def test_generic_question_falls_through_to_today_nutrition():
    p = _profile()
    result = answer_without_ai(p["id"], "how am I doing")
    assert result["data_used"][0]["tool"] == "get_today_nutrition"
    assert "No AI provider is configured" in result["answer"]
