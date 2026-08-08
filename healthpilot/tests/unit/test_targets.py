from app.profile import create_profile
from nutrition.targets import (
    compute_nutrition_targets,
    get_active_target,
    recompute_and_store_target,
)


def _profile(**overrides):
    data = {
        "name": "Test", "age": 35, "sex": "male", "height_cm": 178,
        "current_weight_kg": 82, "activity_level": "moderate", "diet_preference": "non_veg",
        "kidney_disease": "unknown",
    }
    data.update(overrides)
    return create_profile(data)


def test_compute_targets_returns_sane_calories():
    p = _profile()
    t = compute_nutrition_targets(p)
    assert 1200 <= t["calories"] <= 4500


def test_clinician_calorie_target_overrides_computed():
    p = _profile(clinician_calorie_target=2100)
    t = compute_nutrition_targets(p)
    assert t["calories"] == 2100


def test_protein_gate_blocks_very_active_with_unknown_kidney_status():
    p = _profile(activity_level="very_active", kidney_disease="unknown")
    t = compute_nutrition_targets(p)
    assert t["protein_gate_blocked"] is True
    assert t["protein_g"] == round(p["current_weight_kg"] * 0.8, 1)
    assert "clinician" in t["protein_gate_message"].lower()


def test_protein_gate_allows_moderate_activity():
    p = _profile(activity_level="moderate", kidney_disease="unknown")
    t = compute_nutrition_targets(p)
    assert t["protein_gate_blocked"] is False


def test_clinician_protein_target_overrides_gate():
    p = _profile(activity_level="very_active", kidney_disease="unknown", clinician_protein_target_g=140)
    t = compute_nutrition_targets(p)
    assert t["protein_gate_blocked"] is False
    assert t["protein_g"] == 140


def test_sodium_defaults_to_2300_without_clinician_value():
    p = _profile()
    t = compute_nutrition_targets(p)
    assert t["sodium_mg"] == 2300


def test_sodium_uses_clinician_value_when_set():
    p = _profile(clinician_sodium_target_mg=1500)
    t = compute_nutrition_targets(p)
    assert t["sodium_mg"] == 1500


def test_recompute_and_store_persists_and_is_retrievable():
    p = _profile()
    stored = recompute_and_store_target(p)
    fetched = get_active_target(p["id"])
    assert fetched["id"] == stored["id"]
    assert fetched["calories"] == stored["calories"]


def test_no_active_target_before_first_computation():
    p = _profile()
    assert get_active_target(p["id"]) is None
