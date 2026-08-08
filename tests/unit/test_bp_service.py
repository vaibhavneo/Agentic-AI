import datetime as dt

import pytest

from app.profile import create_profile
from safety.events import list_safety_events
from vitals.bp_service import (
    BPValidationError,
    calculate_bp_average,
    calculate_bp_trend,
    get_bp_history,
    record_bp,
)


def _profile():
    return create_profile(
        {
            "name": "Test", "age": 55, "sex": "male", "height_cm": 175,
            "current_weight_kg": 85, "activity_level": "sedentary", "diet_preference": "veg",
        }
    )


def test_record_bp_computes_average_from_two_readings():
    p = _profile()
    reading = record_bp(p["id"], systolic_1=130, diastolic_1=80, systolic_2=140, diastolic_2=90)
    assert reading["average_systolic"] == 135
    assert reading["average_diastolic"] == 85


def test_record_bp_single_reading_average_equals_reading():
    p = _profile()
    reading = record_bp(p["id"], systolic_1=118, diastolic_1=76)
    assert reading["average_systolic"] == 118
    assert reading["average_diastolic"] == 76


def test_record_bp_rejects_impossible_systolic():
    p = _profile()
    with pytest.raises(BPValidationError):
        record_bp(p["id"], systolic_1=500, diastolic_1=80)


def test_record_bp_rejects_impossible_diastolic():
    p = _profile()
    with pytest.raises(BPValidationError):
        record_bp(p["id"], systolic_1=120, diastolic_1=5)


def test_record_bp_rejects_diastolic_greater_than_systolic():
    p = _profile()
    with pytest.raises(BPValidationError):
        record_bp(p["id"], systolic_1=80, diastolic_1=120)


def test_record_bp_rejects_diastolic_equal_to_systolic():
    p = _profile()
    with pytest.raises(BPValidationError):
        record_bp(p["id"], systolic_1=100, diastolic_1=100)


def test_record_bp_rejects_bad_second_reading_diastolic_over_systolic():
    p = _profile()
    with pytest.raises(BPValidationError):
        record_bp(p["id"], systolic_1=120, diastolic_1=80, systolic_2=90, diastolic_2=110)


def test_record_bp_rejects_unknown_symptom():
    p = _profile()
    with pytest.raises(BPValidationError):
        record_bp(p["id"], systolic_1=120, diastolic_1=80, symptoms=["not_real"])


def test_normal_reading_does_not_create_safety_event():
    p = _profile()
    record_bp(p["id"], systolic_1=110, diastolic_1=70)
    assert list_safety_events(p["id"]) == []


def test_crisis_reading_creates_urgent_safety_event():
    p = _profile()
    record_bp(p["id"], systolic_1=190, diastolic_1=125)
    events = list_safety_events(p["id"])
    assert len(events) == 1
    assert events[0]["severity"] == "urgent"
    assert events[0]["event_type"] == "bp_reading"


def test_crisis_with_symptom_flags_emergency_in_stored_reading():
    p = _profile()
    reading = record_bp(p["id"], systolic_1=190, diastolic_1=125, symptoms=["chest_pain"])
    assert reading["emergency"] == 1
    stored = get_bp_history(p["id"])[0]
    assert stored["emergency"] == 1
    assert stored["symptoms"] == ["chest_pain"]


def test_stage_2_reading_creates_warning_safety_event():
    p = _profile()
    record_bp(p["id"], systolic_1=150, diastolic_1=95)
    events = list_safety_events(p["id"])
    assert events[0]["severity"] == "warning"


def test_bp_history_scoped_and_ordered_desc():
    p = _profile()
    day1 = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    day2 = (dt.date.today() - dt.timedelta(days=8)).isoformat()
    record_bp(p["id"], systolic_1=110, diastolic_1=70, reading_date=day1)
    record_bp(p["id"], systolic_1=115, diastolic_1=72, reading_date=day2)
    history = get_bp_history(p["id"], days=365)
    assert [h["reading_date"] for h in history] == [day2, day1]


def test_calculate_bp_average_matches_hand_computed_mean():
    p = _profile()
    record_bp(p["id"], systolic_1=110, diastolic_1=70)
    record_bp(p["id"], systolic_1=130, diastolic_1=90)
    avg = calculate_bp_average(p["id"], days=7)
    assert avg["avg_systolic"] == 120.0
    assert avg["avg_diastolic"] == 80.0
    assert avg["sample_size"] == 2


def test_calculate_bp_average_empty_history():
    p = _profile()
    avg = calculate_bp_average(p["id"], days=7)
    assert avg["sample_size"] == 0
    assert avg["avg_systolic"] is None


def test_calculate_bp_trend_requires_minimum_sample_size():
    p = _profile()
    record_bp(p["id"], systolic_1=120, diastolic_1=80)
    record_bp(p["id"], systolic_1=122, diastolic_1=81)
    trend = calculate_bp_trend(p["id"], days=30)
    assert trend["direction"] == "insufficient_data"


def test_calculate_bp_trend_detects_rising():
    p = _profile()
    today = dt.date.today()
    offsets = [(110, 70, 9), (112, 71, 8), (135, 88, 2), (140, 90, 1)]
    for s, d, days_ago in offsets:
        record_bp(p["id"], systolic_1=s, diastolic_1=d, reading_date=(today - dt.timedelta(days=days_ago)).isoformat())
    trend = calculate_bp_trend(p["id"], days=30)
    assert trend["direction"] == "rising"
    assert trend["systolic_delta"] > 0
