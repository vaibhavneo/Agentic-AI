from app.medication import create_medication, get_today_medication_status, log_dose
from app.profile import create_profile


def _profile():
    return create_profile(
        {
            "name": "Med Status Test", "age": 50, "sex": "male", "height_cm": 175,
            "current_weight_kg": 80, "activity_level": "light", "diet_preference": "veg",
        }
    )


def test_medication_not_logged_today_is_none():
    p = _profile()
    create_medication(p["id"], {"name": "Metformin"})
    status = get_today_medication_status(p["id"])
    assert status[0]["taken_today"] is None


def test_medication_logged_taken_today():
    p = _profile()
    med = create_medication(p["id"], {"name": "Metformin"})
    log_dose(med["id"], p["id"], taken=True)
    status = get_today_medication_status(p["id"])
    assert status[0]["taken_today"] is True


def test_medication_logged_missed_today():
    p = _profile()
    med = create_medication(p["id"], {"name": "Metformin"})
    log_dose(med["id"], p["id"], taken=False)
    status = get_today_medication_status(p["id"])
    assert status[0]["taken_today"] is False


def test_empty_when_no_medications():
    p = _profile()
    assert get_today_medication_status(p["id"]) == []
