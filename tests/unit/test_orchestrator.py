"""Orchestrator tests use a hand-built stub mimicking the OpenAI/DeepSeek SDK
response shape (resp.choices[0].message.{content,tool_calls}) rather than a
live API call — no network access, fully deterministic.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from app.profile import create_profile
from agents import orchestrator


def _profile():
    return create_profile(
        {
            "name": "Orchestrator Test", "age": 41, "sex": "female", "height_cm": 163,
            "current_weight_kg": 70, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def _final_response(text):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call_response(tool_name, arguments, call_id="call_1"):
    fn = SimpleNamespace(name=tool_name, arguments=json.dumps(arguments))
    tc = SimpleNamespace(id=call_id, function=fn)
    message = SimpleNamespace(content="", tool_calls=[tc])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.calls = []

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def test_falls_back_when_ai_not_configured(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    p = _profile()
    result = orchestrator.answer_question(p["id"], "how much protein do I have left")
    assert result["ai_used"] is False


def test_ai_path_returns_final_answer_with_no_tool_calls(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-key")
    p = _profile()
    fake_client = FakeClient([_final_response("You're doing great!")])
    with patch("agents.orchestrator.get_client", return_value=(fake_client, "deepseek")):
        result = orchestrator.answer_question(p["id"], "how am I doing")
    assert result["ai_used"] is True
    assert result["answer"] == "You're doing great!"
    assert result["data_used"] == []


def test_ai_path_executes_tool_call_and_feeds_result_back(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-key")
    p = _profile()
    fake_client = FakeClient([
        _tool_call_response("get_today_nutrition", {}),
        _final_response("You've logged nothing yet today."),
    ])
    with patch("agents.orchestrator.get_client", return_value=(fake_client, "deepseek")):
        result = orchestrator.answer_question(p["id"], "how am I doing")
    assert result["ai_used"] is True
    assert len(result["data_used"]) == 1
    assert result["data_used"][0]["tool"] == "get_today_nutrition"
    assert result["data_used"][0]["result"]["meal_count"] == 0
    assert len(fake_client.calls) == 2  # one call that requested the tool, one final call


def test_ai_path_rejects_tool_not_in_specialist_allowlist(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-key")
    p = _profile()
    # "record_bp" isn't a registered tool at all (mutating tools are excluded from chat)
    fake_client = FakeClient([
        _tool_call_response("record_bp", {"systolic_1": 200, "diastolic_1": 130}),
        _final_response("done"),
    ])
    with patch("agents.orchestrator.get_client", return_value=(fake_client, "deepseek")):
        result = orchestrator.answer_question(p["id"], "how am I doing")
    assert "error" in result["data_used"][0]["result"]


def test_ai_path_gives_up_after_max_iterations(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-key")
    p = _profile()
    # always returns a tool call, never a final answer — should stop at MAX_TOOL_ITERATIONS
    responses = [_tool_call_response("get_today_nutrition", {}) for _ in range(orchestrator.MAX_TOOL_ITERATIONS)]
    fake_client = FakeClient(responses)
    with patch("agents.orchestrator.get_client", return_value=(fake_client, "deepseek")):
        result = orchestrator.answer_question(p["id"], "how am I doing")
    assert "tool-call budget" in result["answer"]
    assert len(result["data_used"]) == orchestrator.MAX_TOOL_ITERATIONS


def test_ai_call_exception_falls_back_gracefully(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-key")
    p = _profile()

    def _raise(**kwargs):
        raise RuntimeError("network error")

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_raise)))
    with patch("agents.orchestrator.get_client", return_value=(fake_client, "deepseek")):
        result = orchestrator.answer_question(p["id"], "how much protein do I have left")
    assert result["ai_used"] is False


def test_tool_call_never_lets_model_override_profile_id(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-key")
    a = _profile()
    b = _profile()
    fake_client = FakeClient([
        _tool_call_response("get_user_profile", {"profile_id": b["id"]}),
        _final_response("ok"),
    ])
    with patch("agents.orchestrator.get_client", return_value=(fake_client, "deepseek")):
        result = orchestrator.answer_question(a["id"], "tell me about my profile")
    assert result["data_used"][0]["result"]["id"] == a["id"]
