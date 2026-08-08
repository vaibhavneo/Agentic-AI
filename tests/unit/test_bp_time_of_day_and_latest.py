from app.profile import create_profile
from vitals.bp_service import (
    classify_time_of_day,
    get_latest_bp_reading,
    get_today_bp_average,
    record_bp,
)


def _profile():
    return create_profile(
        {
            "name": "TOD Test", "age": 44, "sex": "female", "height_cm": 162,
            "current_weight_kg": 60, "activity_level": "light", "diet_preference": "veg",
        }
    )


def test_classify_time_of_day_morning():
    assert classify_time_of_day("07:30") == "morning"
    assert classify_time_of_day("11:59") == "morning"


def test_classify_time_of_day_evening():
    assert classify_time_of_day("12:00") == "evening"
    assert classify_time_of_day("20:15") == "evening"


def test_classify_time_of_day_unspecified():
    assert classify_time_of_day(None) == "unspecified"
    assert classify_time_of_day("") == "unspecified"


def test_reading_carries_time_of_day():
    p = _profile()
    reading = record_bp(p["id"], systolic_1=118, diastolic_1=76, reading_time="07:00")
    assert reading["time_of_day"] == "morning"


def test_get_latest_bp_reading_finds_most_recent_even_if_not_today():
    import datetime as dt
    p = _profile()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    record_bp(p["id"], systolic_1=120, diastolic_1=80, reading_date=yesterday)
    latest = get_latest_bp_reading(p["id"])
    assert latest is not None
    assert latest["reading_date"] == yesterday


def test_get_latest_bp_reading_none_when_no_readings():
    p = _profile()
    assert get_latest_bp_reading(p["id"]) is None


def test_get_today_bp_average_only_counts_today():
    import datetime as dt
    p = _profile()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    record_bp(p["id"], systolic_1=130, diastolic_1=85, reading_date=yesterday)
    record_bp(p["id"], systolic_1=110, diastolic_1=70)  # today
    avg = get_today_bp_average(p["id"])
    assert avg["sample_size"] == 1
    assert avg["avg_systolic"] == 110.0
