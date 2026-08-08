from app.profile import create_profile
from insights.health_score import compute_health_score
from nutrition.targets import recompute_and_store_target


def _profile():
    return create_profile(
        {
            "name": "Score Test", "age": 33, "sex": "male", "height_cm": 175,
            "current_weight_kg": 78, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_health_score_never_produces_a_single_combined_number():
    p = _profile()
    result = compute_health_score(p["id"])
    assert "components" in result
    assert "score" not in result  # top level must not have one opaque score
    expected_components = {
        "nutrition_quality", "sodium_management", "protein_adequacy", "fiber",
        "activity", "strength", "sleep", "plan_adherence",
    }
    assert set(result["components"].keys()) == expected_components


def test_every_component_has_score_and_visible_inputs():
    p = _profile()
    result = compute_health_score(p["id"])
    for name, component in result["components"].items():
        assert 0 <= component["score"] <= 100, name
        assert "inputs" in component and isinstance(component["inputs"], dict), name


def test_zero_data_scores_are_all_zero_not_fabricated():
    p = _profile()
    result = compute_health_score(p["id"])
    for name, component in result["components"].items():
        assert component["score"] == 0, f"{name} should be 0 with no data logged"


def test_protein_adequacy_reflects_real_target_ratio():
    p = _profile()
    recompute_and_store_target(p)
    result = compute_health_score(p["id"])
    # still zero — no meals logged yet, even though a target exists
    assert result["components"]["protein_adequacy"]["score"] == 0
