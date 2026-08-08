import pytest

from app.profile import (
    ValidationError,
    create_profile,
    delete_profile,
    get_profile,
    list_profiles,
    update_profile,
)


def _valid_profile(**overrides):
    data = {
        "name": "Asha",
        "age": 45,
        "sex": "female",
        "height_cm": 162,
        "current_weight_kg": 68,
        "activity_level": "moderate",
        "diet_preference": "veg",
        "meals_per_day": 3,
    }
    data.update(overrides)
    return data


def test_create_and_get_profile():
    p = create_profile(_valid_profile())
    assert p["name"] == "Asha"
    assert p["kidney_disease"] == "unknown"  # default, never inferred
    fetched = get_profile(p["id"])
    assert fetched == p


def test_unknown_kidney_disease_is_valid_default():
    p = create_profile(_valid_profile())
    assert p["kidney_disease"] == "unknown"
    assert p["egfr"] is None
    assert p["potassium_mmol_l"] is None


def test_rejects_missing_name():
    with pytest.raises(ValidationError):
        create_profile(_valid_profile(name=""))


def test_rejects_impossible_age():
    with pytest.raises(ValidationError):
        create_profile(_valid_profile(age=200))


def test_rejects_impossible_height():
    with pytest.raises(ValidationError):
        create_profile(_valid_profile(height_cm=1000))


def test_rejects_invalid_sex():
    with pytest.raises(ValidationError):
        create_profile(_valid_profile(sex="unspecified"))


def test_rejects_invalid_kidney_disease_value():
    with pytest.raises(ValidationError):
        create_profile(_valid_profile(kidney_disease="maybe"))


def test_rejects_bad_time_format():
    with pytest.raises(ValidationError):
        create_profile(_valid_profile(wake_time="25:99"))


def test_allergies_round_trip_as_list():
    p = create_profile(_valid_profile(allergies=["peanuts", "shellfish"]))
    assert p["allergies"] == ["peanuts", "shellfish"]


def test_update_profile_merges_fields():
    p = create_profile(_valid_profile())
    updated = update_profile(p["id"], {"age": 46})
    assert updated["age"] == 46
    assert updated["name"] == "Asha"


def test_update_nonexistent_profile_raises():
    with pytest.raises(ValidationError):
        update_profile("does-not-exist", {"age": 50})


def test_delete_profile_removes_it():
    p = create_profile(_valid_profile())
    delete_profile(p["id"])
    assert get_profile(p["id"]) is None


def test_list_profiles_returns_all():
    create_profile(_valid_profile(name="A"))
    create_profile(_valid_profile(name="B"))
    names = {p["name"] for p in list_profiles()}
    assert names == {"A", "B"}


def test_clinician_targets_optional_but_validated():
    with pytest.raises(ValidationError):
        create_profile(_valid_profile(clinician_sodium_target_mg=99999))
    p = create_profile(_valid_profile(clinician_sodium_target_mg=1800))
    assert p["clinician_sodium_target_mg"] == 1800


def test_primary_health_goals_and_exercise_limitations_optional_and_stored():
    p = create_profile(_valid_profile(
        primary_health_goals="Lower blood pressure", exercise_limitations="Bad left knee",
    ))
    assert p["primary_health_goals"] == "Lower blood pressure"
    assert p["exercise_limitations"] == "Bad left knee"


def test_primary_health_goals_blank_normalizes_to_none():
    p = create_profile(_valid_profile(primary_health_goals="   "))
    assert p["primary_health_goals"] is None


def test_primary_health_goals_omitted_defaults_to_none():
    p = create_profile(_valid_profile())
    assert p["primary_health_goals"] is None
    assert p["exercise_limitations"] is None
