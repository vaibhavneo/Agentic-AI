"""No AI provider is configured in the test environment (see conftest —
DEEPSEEK_API_KEY is unset), so these exercise the heuristic fallback parser.
The AI-enabled path is exercised structurally via mocked chat_json in
test_nl_logging_ai_path.
"""
from unittest.mock import patch

from app.profile import create_profile
from nutrition.nl_logging import log_food_from_text, parse_food_text


def _profile():
    return create_profile(
        {
            "name": "Test", "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_heuristic_parse_splits_on_and_and_commas():
    candidates = parse_food_text("banana, rice and dal")
    queries = [c["query"] for c in candidates]
    assert queries == ["banana", "rice", "dal"]


def test_parse_empty_text_returns_no_candidates():
    assert parse_food_text("") == []
    assert parse_food_text("   ") == []


def test_log_food_from_text_resolves_known_foods():
    p = _profile()
    result = log_food_from_text(p["id"], "breakfast", "banana")
    assert len(result["logged"]) == 1
    assert result["logged"][0]["food_name"].lower().startswith("banana")
    assert result["unresolved"] == []


def test_log_food_from_text_flags_unresolved_candidates():
    p = _profile()
    result = log_food_from_text(p["id"], "lunch", "some totally made up food xyz123")
    assert result["logged"] == []
    assert len(result["unresolved"]) == 1


def test_log_food_from_text_never_invents_nutrition_for_unresolved():
    p = _profile()
    result = log_food_from_text(p["id"], "lunch", "zzz_nonexistent_food")
    assert all("nutrition" not in item for item in result["unresolved"])


@patch("agents.llm_client.chat_json")
def test_ai_path_used_when_configured(mock_chat_json, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-key-for-test")
    mock_chat_json.return_value = {"candidates": [{"query": "banana", "quantity": 2}]}

    candidates = parse_food_text("two bananas")
    assert candidates == [{"query": "banana", "quantity": 2}]
    mock_chat_json.assert_called_once()


@patch("agents.llm_client.chat_json")
def test_ai_failure_falls_back_to_heuristic(mock_chat_json, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-key-for-test")
    mock_chat_json.side_effect = RuntimeError("network error")

    candidates = parse_food_text("banana and rice")
    assert [c["query"] for c in candidates] == ["banana", "rice"]
