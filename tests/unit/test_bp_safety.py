"""BP safety engine — the safety-critical module for the M3 checkpoint.
Exhaustively tests classification boundaries (off-by-one is a real clinical
risk here), the crisis+symptom emergency escalation rule, and that no
message ever names a medication/exercise/diet action as an acute response.
"""
import pytest

from safety.bp_safety import BPSafetyError, classify_bp, evaluate_bp_reading, validate_symptoms
from safety.constants import BP_EMERGENCY_SYMPTOMS

# Words that would indicate the engine is suggesting an acute clinical
# intervention — never allowed in any bp_safety message.
FORBIDDEN_WORDS = [
    "medication", "medicine", "drug", "dose", "pill", "tablet",
    "exercise", "workout", "walk", "run",
    "diet", "food", "eat", "sodium", "salt", "potassium",
]


# --- classify_bp boundary tests --------------------------------------------

@pytest.mark.parametrize("systolic,diastolic,expected", [
    (90, 60, "normal"),
    (119, 79, "normal"),
    (120, 79, "elevated"),
    (129, 79, "elevated"),
    (130, 79, "stage_1"),          # systolic alone crosses into stage_1
    (119, 80, "stage_1"),          # diastolic alone crosses into stage_1
    (139, 89, "stage_1"),
    (140, 89, "stage_2"),          # systolic alone crosses into stage_2
    (139, 90, "stage_2"),          # diastolic alone crosses into stage_2
    (179, 119, "stage_2"),
    (180, 100, "crisis"),          # systolic alone crosses into crisis
    (150, 120, "crisis"),          # diastolic alone crosses into crisis
    (200, 130, "crisis"),
])
def test_classify_bp_boundaries(systolic, diastolic, expected):
    assert classify_bp(systolic, diastolic) == expected


def test_classify_bp_takes_more_severe_of_the_two_numbers():
    # normal diastolic but crisis-range systolic must still be 'crisis'
    assert classify_bp(185, 70) == "crisis"
    # normal systolic but crisis-range diastolic must still be 'crisis'
    assert classify_bp(110, 125) == "crisis"


# --- symptom validation ------------------------------------------------

def test_validate_symptoms_accepts_known_symptoms():
    result = validate_symptoms(["chest_pain", "confusion"])
    assert result == ["chest_pain", "confusion"]


def test_validate_symptoms_rejects_unknown_value():
    with pytest.raises(BPSafetyError):
        validate_symptoms(["chest_pain", "made_up_symptom"])


def test_validate_symptoms_none_becomes_empty_list():
    assert validate_symptoms(None) == []


def test_all_emergency_symptoms_individually_valid():
    for symptom in BP_EMERGENCY_SYMPTOMS:
        assert validate_symptoms([symptom]) == [symptom]


# --- evaluate_bp_reading: category -> urgency mapping -----------------

def test_normal_reading_is_info_no_escalation():
    result = evaluate_bp_reading(110, 70)
    assert result["urgency"] == "info"
    assert result["emergency"] is False
    assert result["repeat_measurement_recommended"] is False


def test_stage_2_reading_is_warning_with_repeat_measurement():
    result = evaluate_bp_reading(150, 95)
    assert result["urgency"] == "warning"
    assert result["repeat_measurement_recommended"] is True
    assert result["emergency"] is False


def test_crisis_without_symptoms_is_urgent_not_emergency():
    result = evaluate_bp_reading(190, 125)
    assert result["category"] == "crisis"
    assert result["urgency"] == "urgent"
    assert result["emergency"] is False
    assert result["repeat_measurement_recommended"] is True


def test_crisis_with_symptom_is_emergency():
    result = evaluate_bp_reading(190, 125, symptoms=["chest_pain"])
    assert result["emergency"] is True
    assert result["urgency"] == "urgent"
    assert "emergency" in result["message"].lower()


def test_crisis_emergency_skips_repeat_measurement_advice():
    """Once it's an emergency, the message must not tell the user to wait
    and re-measure — that could delay seeking care."""
    result = evaluate_bp_reading(190, 125, symptoms=["severe_headache"])
    assert result["repeat_measurement_recommended"] is False


def test_symptoms_alone_without_crisis_range_never_trigger_emergency():
    """A symptom checked on a normal/elevated/stage_1/stage_2 reading must
    NOT escalate to emergency — only crisis-range + symptom does."""
    for systolic, diastolic in [(110, 70), (125, 78), (135, 85), (150, 95)]:
        result = evaluate_bp_reading(systolic, diastolic, symptoms=["chest_pain"])
        assert result["emergency"] is False, f"{systolic}/{diastolic} + symptom incorrectly flagged emergency"


def test_crisis_reading_always_gets_escalation_guidance_regardless_of_symptoms():
    no_symptoms = evaluate_bp_reading(185, 122)
    assert no_symptoms["urgency"] == "urgent"
    assert no_symptoms["repeat_measurement_recommended"] is True


@pytest.mark.parametrize("systolic,diastolic,symptoms", [
    (110, 70, None),
    (125, 78, ["chest_pain"]),
    (150, 95, None),
    (185, 122, None),
    (185, 122, ["chest_pain"]),
    (200, 130, ["confusion", "vision_changes"]),
])
def test_no_message_ever_suggests_acute_medication_exercise_or_diet(systolic, diastolic, symptoms):
    result = evaluate_bp_reading(systolic, diastolic, symptoms)
    message_lower = result["message"].lower()
    for word in FORBIDDEN_WORDS:
        assert word not in message_lower, f"forbidden word '{word}' found in message: {result['message']}"


def test_invalid_symptom_raises_before_classification():
    with pytest.raises(BPSafetyError):
        evaluate_bp_reading(120, 80, symptoms=["not_a_real_symptom"])
