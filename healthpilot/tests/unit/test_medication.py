import pytest

from app.medication import (
    ValidationError,
    create_medication,
    delete_medication,
    get_medication_context,
    list_medications,
    log_dose,
    update_medication,
)
from app.profile import create_profile


def _profile():
    return create_profile(
        {
            "name": "Ravi",
            "age": 60,
            "sex": "male",
            "height_cm": 170,
            "current_weight_kg": 80,
            "activity_level": "light",
            "diet_preference": "non_veg",
        }
    )


def test_auto_flags_arb_as_potassium_risk():
    p = _profile()
    med = create_medication(p["id"], {"name": "Valsartan", "dose": "80mg", "frequency": "once daily"})
    assert med["potassium_risk"] == 1
    assert med["potassium_risk_source"] == "auto"


def test_does_not_flag_unrelated_medication():
    p = _profile()
    med = create_medication(p["id"], {"name": "Atorvastatin", "dose": "20mg"})
    assert med["potassium_risk"] == 0
    assert med["potassium_risk_source"] == "none"


def test_manual_override_can_flag_unknown_drug():
    p = _profile()
    med = create_medication(p["id"], {"name": "SomeOtherDrug", "potassium_risk_manual": True})
    assert med["potassium_risk"] == 1
    assert med["potassium_risk_source"] == "manual"


def test_no_medication_name_rejected():
    p = _profile()
    with pytest.raises(ValidationError):
        create_medication(p["id"], {"name": ""})


def test_medication_scoped_to_profile():
    p1 = _profile()
    p2 = create_profile(
        {
            "name": "Meera", "age": 30, "sex": "female", "height_cm": 160,
            "current_weight_kg": 55, "activity_level": "active", "diet_preference": "veg",
        }
    )
    create_medication(p1["id"], {"name": "Lisinopril"})
    assert len(list_medications(p1["id"], active_only=False)) == 1
    assert len(list_medications(p2["id"], active_only=False)) == 0


def test_log_dose_and_context():
    p = _profile()
    med = create_medication(p["id"], {"name": "Losartan"})
    log = log_dose(med["id"], p["id"], taken=True)
    assert log["taken"] == 1
    ctx = get_medication_context(p["id"])
    assert ctx["has_potassium_risk_medication"] is True
    assert len(ctx["active_medications"]) == 1


def test_delete_medication():
    p = _profile()
    med = create_medication(p["id"], {"name": "Metformin"})
    delete_medication(med["id"], p["id"])
    assert list_medications(p["id"], active_only=False) == []


def test_update_medication_name_recomputes_auto_flag():
    p = _profile()
    med = create_medication(p["id"], {"name": "Metformin"})
    assert med["potassium_risk"] == 0
    updated = update_medication(med["id"], p["id"], {"name": "Spironolactone"})
    assert updated["potassium_risk"] == 1
    assert updated["potassium_risk_source"] == "auto"
