"""SQL injection resistance (parameterized queries throughout), and a check
that the CSV import / export endpoints never build a filesystem path from
client-supplied input — the simplest possible path-traversal defense is not
taking a path from the user at all, which is what app/csv_import.py and
app/data_export.py do (process in memory / stream the response directly).
"""
import io

import pytest

from app.profile import ValidationError, create_profile, get_profile
from app.csv_import import import_bp_csv
from nutrition.food_service import search_food


def test_profile_name_with_sql_metacharacters_is_stored_literally():
    injection_attempt = "Robert'); DROP TABLE profiles;--"
    p = create_profile(
        {
            "name": injection_attempt, "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
        }
    )
    fetched = get_profile(p["id"])
    assert fetched["name"] == injection_attempt  # stored as literal data, not executed as SQL

    # table must still exist and be queryable — a real injection would have dropped it
    still_works = create_profile(
        {
            "name": "Sanity Check", "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
        }
    )
    assert get_profile(still_works["id"]) is not None


def test_food_search_with_sql_metacharacters_does_not_error():
    results = search_food("banana'; DROP TABLE foods;--", use_provider=False)
    assert results == []  # no match, no crash, table untouched
    assert search_food("banana", use_provider=False) != []


def test_medication_name_with_sql_metacharacters_stored_literally():
    from app.medication import create_medication
    p = create_profile(
        {
            "name": "Test", "age": 40, "sex": "female", "height_cm": 165,
            "current_weight_kg": 60, "activity_level": "light", "diet_preference": "veg",
        }
    )
    injection_attempt = "Aspirin'); DELETE FROM medications;--"
    med = create_medication(p["id"], {"name": injection_attempt})
    assert med["name"] == injection_attempt


def test_csv_import_never_touches_a_client_supplied_filename():
    """The import functions take a file-like stream, never a path/filename
    string — there is no code path where client input becomes a filesystem
    path, so classic path traversal (../../etc/passwd) doesn't apply here."""
    import inspect
    from app import csv_import

    sig = inspect.signature(csv_import.import_bp_csv)
    assert "path" not in sig.parameters
    assert "filename" not in sig.parameters
    assert "file_stream" in sig.parameters


def test_csv_import_with_path_traversal_like_content_is_just_rejected_data():
    """Even if someone crafts a CSV whose field values look like a path
    traversal payload, it's just a malformed data value — reject it,
    don't do anything filesystem-related with it."""
    p = create_profile(
        {
            "name": "Traversal Test", "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
        }
    )
    csv_text = "date,time,systolic_1,diastolic_1,pulse_1,systolic_2,diastolic_2,pulse_2,symptoms,notes\n../../../etc/passwd,08:00,120,80,,,,,,\n"
    result = import_bp_csv(p["id"], io.BytesIO(csv_text.encode()))
    # the bogus "date" value just fails record_bp's validation as bad data
    assert result["imported"] == 0
    assert len(result["errors"]) == 1
