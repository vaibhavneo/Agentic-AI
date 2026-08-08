import datetime as dt

import pytest

from app.profile import create_profile
from vitals.other_vitals_service import (
    OtherVitalsValidationError,
    get_other_vitals_history,
    record_other_vitals,
)
from vitals.sleep_service import SleepValidationError, get_sleep_history, record_sleep
from vitals.weight_service import (
    WeightValidationError,
    calculate_weight_trend,
    get_weight_history,
    record_weight,
)


def _profile():
    return create_profile(
        {
            "name": "Test", "age": 45, "sex": "female", "height_cm": 160,
            "current_weight_kg": 70, "activity_level": "light", "diet_preference": "veg",
        }
    )


def test_record_weight_and_history():
    p = _profile()
    record_weight(p["id"], 70.5)
    record_weight(p["id"], 70.2)
    history = get_weight_history(p["id"])
    assert len(history) == 2


def test_record_weight_rejects_out_of_range():
    p = _profile()
    with pytest.raises(WeightValidationError):
        record_weight(p["id"], 5)


def test_weight_trend_detects_falling():
    p = _profile()
    today = dt.date.today()
    record_weight(p["id"], 75, log_date=(today - dt.timedelta(days=10)).isoformat())
    record_weight(p["id"], 73, log_date=(today - dt.timedelta(days=1)).isoformat())
    trend = calculate_weight_trend(p["id"], days=30)
    assert trend["direction"] == "falling"
    assert trend["delta_kg"] == -2


def test_record_sleep_and_history():
    p = _profile()
    record_sleep(p["id"], 7.5, quality=4)
    history = get_sleep_history(p["id"])
    assert history[0]["hours"] == 7.5
    assert history[0]["quality"] == 4


def test_record_sleep_rejects_bad_quality():
    p = _profile()
    with pytest.raises(SleepValidationError):
        record_sleep(p["id"], 7, quality=10)


def test_record_sleep_rejects_impossible_hours():
    p = _profile()
    with pytest.raises(SleepValidationError):
        record_sleep(p["id"], 30)


def test_record_other_vitals_requires_at_least_one_field():
    p = _profile()
    with pytest.raises(OtherVitalsValidationError):
        record_other_vitals(p["id"])


def test_record_other_vitals_partial_fields_ok():
    p = _profile()
    record_other_vitals(p["id"], resting_hr=62)
    history = get_other_vitals_history(p["id"])
    assert history[0]["resting_hr"] == 62
    assert history[0]["waist_cm"] is None


def test_record_other_vitals_rejects_out_of_range_spo2():
    p = _profile()
    with pytest.raises(OtherVitalsValidationError):
        record_other_vitals(p["id"], spo2_pct=20)
