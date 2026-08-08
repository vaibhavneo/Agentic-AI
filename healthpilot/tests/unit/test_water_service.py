import pytest

from app.profile import create_profile
from nutrition.water_service import WaterValidationError, get_today_water, log_water


def _profile():
    return create_profile(
        {
            "name": "Test", "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_log_water_accumulates():
    p = _profile()
    log_water(p["id"], 250)
    log_water(p["id"], 250)
    assert get_today_water(p["id"]) == 500


def test_log_water_rejects_non_positive():
    p = _profile()
    with pytest.raises(WaterValidationError):
        log_water(p["id"], 0)


def test_water_scoped_per_profile():
    a, b = _profile(), _profile()
    log_water(a["id"], 500)
    assert get_today_water(b["id"]) == 0
