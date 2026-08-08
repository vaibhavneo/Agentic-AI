import io

from app.profile import create_profile
from app.csv_import import (
    CSV_TEMPLATES,
    import_bp_csv,
    import_exercise_csv,
    import_sleep_csv,
    import_weight_csv,
)
from vitals.bp_service import get_bp_history
from vitals.sleep_service import get_sleep_history
from vitals.weight_service import get_weight_history
from exercise.activity_service import list_workouts


def _profile():
    return create_profile(
        {
            "name": "CSV Test", "age": 44, "sex": "male", "height_cm": 176,
            "current_weight_kg": 88, "activity_level": "sedentary", "diet_preference": "non_veg",
        }
    )


def _stream(text):
    return io.BytesIO(text.encode("utf-8"))


def test_bp_template_imports_cleanly():
    p = _profile()
    result = import_bp_csv(p["id"], _stream(CSV_TEMPLATES["bp"]))
    assert result["imported"] == 1
    assert result["errors"] == []
    assert len(get_bp_history(p["id"], days=36500)) == 1


def test_bp_import_rejects_impossible_row_but_keeps_valid_ones():
    csv_text = (
        "date,time,systolic_1,diastolic_1,pulse_1,systolic_2,diastolic_2,pulse_2,symptoms,notes\n"
        "2026-01-01,08:00,120,80,,,,,,\n"
        "2026-01-02,08:00,500,80,,,,,,\n"  # impossible systolic
        "2026-01-03,08:00,80,120,,,,,,\n"  # diastolic > systolic
    )
    p = _profile()
    result = import_bp_csv(p["id"], _stream(csv_text))
    assert result["imported"] == 1
    assert len(result["errors"]) == 2
    assert result["errors"][0]["row"] == 3
    assert result["errors"][1]["row"] == 4


def test_bp_import_rejects_unknown_symptom():
    csv_text = (
        "date,time,systolic_1,diastolic_1,pulse_1,systolic_2,diastolic_2,pulse_2,symptoms,notes\n"
        "2026-01-01,08:00,120,80,,,,,made_up_symptom,\n"
    )
    p = _profile()
    result = import_bp_csv(p["id"], _stream(csv_text))
    assert result["imported"] == 0
    assert len(result["errors"]) == 1


def test_weight_template_imports_cleanly():
    p = _profile()
    result = import_weight_csv(p["id"], _stream(CSV_TEMPLATES["weight"]))
    assert result["imported"] == 1
    assert get_weight_history(p["id"], days=36500)[0]["weight_kg"] == 72.4


def test_weight_import_rejects_out_of_range():
    csv_text = "date,weight_kg,notes\n2026-01-01,5,\n"
    p = _profile()
    result = import_weight_csv(p["id"], _stream(csv_text))
    assert result["imported"] == 0
    assert len(result["errors"]) == 1


def test_weight_import_rejects_non_numeric_value():
    csv_text = "date,weight_kg,notes\n2026-01-01,not-a-number,\n"
    p = _profile()
    result = import_weight_csv(p["id"], _stream(csv_text))
    assert result["imported"] == 0
    assert len(result["errors"]) == 1


def test_sleep_template_imports_cleanly():
    p = _profile()
    result = import_sleep_csv(p["id"], _stream(CSV_TEMPLATES["sleep"]))
    assert result["imported"] == 1
    assert get_sleep_history(p["id"], days=36500)[0]["hours"] == 7.5


def test_sleep_import_rejects_impossible_hours():
    csv_text = "date,hours,quality,notes\n2026-01-01,30,3,\n"
    p = _profile()
    result = import_sleep_csv(p["id"], _stream(csv_text))
    assert result["imported"] == 0


def test_exercise_template_imports_cleanly():
    p = _profile()
    result = import_exercise_csv(p["id"], _stream(CSV_TEMPLATES["exercise"]))
    assert result["imported"] == 1
    assert len(list_workouts(p["id"], "1970-01-01")) == 1


def test_exercise_import_rejects_cardio_without_intensity():
    csv_text = (
        "date,workout_type,activity,duration_min,distance_km,steps,avg_hr,max_hr,rpe,intensity,wearable_calories,notes\n"
        "2026-01-01,cardio,running,30,5,,,,,,\n"
    )
    p = _profile()
    result = import_exercise_csv(p["id"], _stream(csv_text))
    assert result["imported"] == 0
    assert len(result["errors"]) == 1


def test_empty_csv_raises():
    from app.csv_import import CsvImportError
    import pytest
    p = _profile()
    with pytest.raises(CsvImportError):
        import_bp_csv(p["id"], _stream(""))


def test_csv_import_scoped_to_profile():
    a, b = _profile(), _profile()
    import_bp_csv(a["id"], _stream(CSV_TEMPLATES["bp"]))
    assert len(get_bp_history(a["id"], days=36500)) == 1
    assert len(get_bp_history(b["id"], days=36500)) == 0
