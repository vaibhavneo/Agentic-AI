"""
Regression tests for the reasoning-leak bug found in manual browser testing:
deepseek-v4-flash is actually reasoning-capable and, under a tight
max_tokens budget, can return an empty `content` with the chain-of-thought
in a separate `reasoning_content` field instead — a previous fallback then
displayed that raw reasoning to the user as if it were the final answer
(e.g. "I need to check my data...", "Actually, that's not exactly right
either" showing up mid-chat).

Fix: pass extra_body={"thinking": {"type": "disabled"}} on every DeepSeek
call (confirmed empirically against the real API — see PROGRESS_LOG.md) so
`content` is always the direct answer. These tests verify the parameter is
actually wired into both call sites, using a mocked OpenAI client (no real
API calls, no network dependency).
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI

import web.app as app_module
import agents.prediction_engine as prediction_engine


def _mock_response(content="A clean final answer.", reasoning_content=None, finish_reason="stop"):
    message = SimpleNamespace(content=content, reasoning_content=reasoning_content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class TestWebAppReasoningDisabled(unittest.TestCase):
    def test_chat_with_client_passes_thinking_disabled(self):
        client = OpenAI(api_key="fake-key-for-test")
        client.chat.completions.create = MagicMock(return_value=_mock_response())

        answer = app_module._chat_with_client(client, "system prompt", [{"role": "user", "content": "hi"}])

        self.assertEqual(answer, "A clean final answer.")
        _, kwargs = client.chat.completions.create.call_args
        self.assertEqual(kwargs.get("extra_body"), {"thinking": {"type": "disabled"}})

    def test_chat_with_client_still_falls_back_if_content_somehow_empty(self):
        # Last-resort safety net: should not normally trigger with thinking
        # disabled, but must not crash if it ever does.
        client = OpenAI(api_key="fake-key-for-test")
        client.chat.completions.create = MagicMock(
            return_value=_mock_response(content="", reasoning_content="leftover reasoning", finish_reason="length"))

        answer = app_module._chat_with_client(client, "system prompt", [{"role": "user", "content": "hi"}])
        self.assertEqual(answer, "leftover reasoning")


class TestPredictionEngineReasoningDisabled(unittest.TestCase):
    def test_call_passes_thinking_disabled(self):
        client = OpenAI(api_key="fake-key-for-test")
        client.chat.completions.create = MagicMock(return_value=_mock_response())

        answer = prediction_engine._call(client, "system", "user question")

        self.assertEqual(answer, "A clean final answer.")
        _, kwargs = client.chat.completions.create.call_args
        self.assertEqual(kwargs.get("extra_body"), {"thinking": {"type": "disabled"}})


if __name__ == "__main__":
    unittest.main()
