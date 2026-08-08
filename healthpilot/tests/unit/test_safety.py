from safety.potassium_safety import (
    can_auto_recommend_potassium_supplement,
    classify_medication_potassium_risk,
)
from safety.protein_safety import check_protein_target_safety, is_high_protein_target


def test_classify_arb_variants():
    for name in ["Valsartan", "losartan potassium", "Irbesartan 150mg"]:
        assert classify_medication_potassium_risk(name) is True


def test_classify_unrelated_drug():
    assert classify_medication_potassium_risk("Amlodipine") is False


def test_classify_empty_name():
    assert classify_medication_potassium_risk("") is False


def test_blocks_potassium_supplement_when_on_arb():
    meds = [{"name": "Valsartan", "active": True, "potassium_risk": True}]
    allowed, reason = can_auto_recommend_potassium_supplement(meds)
    assert allowed is False
    assert reason is not None


def test_allows_potassium_supplement_when_no_risk_meds():
    meds = [{"name": "Atorvastatin", "active": True, "potassium_risk": False}]
    allowed, reason = can_auto_recommend_potassium_supplement(meds)
    assert allowed is True
    assert reason is None


def test_inactive_potassium_risk_medication_does_not_block():
    meds = [{"name": "Valsartan", "active": False, "potassium_risk": True}]
    allowed, _ = can_auto_recommend_potassium_supplement(meds)
    assert allowed is True


def test_is_high_protein_target():
    assert is_high_protein_target(target_g_per_day=112, weight_kg=70) is True  # 1.6 g/kg
    assert is_high_protein_target(target_g_per_day=70, weight_kg=70) is False


def test_protein_gate_blocks_high_protein_with_unknown_kidney_status():
    allowed, msg = check_protein_target_safety(
        target_g_per_day=120, weight_kg=70, kidney_disease="unknown", clinician_protein_target_g=None
    )
    assert allowed is False
    assert "clinician" in msg.lower()


def test_protein_gate_blocks_high_protein_with_known_kidney_disease():
    allowed, msg = check_protein_target_safety(
        target_g_per_day=120, weight_kg=70, kidney_disease="yes", clinician_protein_target_g=None
    )
    assert allowed is False


def test_protein_gate_allows_moderate_target_regardless_of_kidney_status():
    allowed, msg = check_protein_target_safety(
        target_g_per_day=70, weight_kg=70, kidney_disease="unknown", clinician_protein_target_g=None
    )
    assert allowed is True
    assert msg is None


def test_protein_gate_clinician_target_always_overrides():
    allowed, msg = check_protein_target_safety(
        target_g_per_day=150, weight_kg=70, kidney_disease="unknown", clinician_protein_target_g=150
    )
    assert allowed is True
    assert msg is None
