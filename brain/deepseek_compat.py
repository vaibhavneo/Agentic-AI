from __future__ import annotations
"""
DeepSeek → Anthropic compatibility shim.
Wraps OpenAI client (DeepSeek) to match the Anthropic messages.create() interface
that base_agent.py uses, including tool_use stop_reason and content blocks.
"""
import json
import uuid
from types import SimpleNamespace
from typing import Any


class _ContentBlock:
    def __init__(self, type_, text=None, id=None, name=None, input=None):
        self.type  = type_
        self.text  = text or ""
        self.id    = id or str(uuid.uuid4())
        self.name  = name
        self.input = input or {}


class _Usage:
    def __init__(self, inp, out):
        self.input_tokens  = inp
        self.output_tokens = out


class _Response:
    def __init__(self, content, stop_reason, usage):
        self.content     = content
        self.stop_reason = stop_reason
        self.usage       = usage


def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schema → OpenAI function schema."""
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            }
        })
    return result


def _messages_to_openai(messages: list[dict]) -> list[dict]:
    """Convert Anthropic message list → OpenAI message list."""
    out = []
    for m in messages:
        role = m["role"]
        content = m["content"]

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            # Anthropic assistant messages can contain tool_use blocks
            if role == "assistant":
                text_parts = [b.text for b in content if hasattr(b, "text") and b.text]
                tool_calls = []
                for b in content:
                    if hasattr(b, "type") and b.type == "tool_use":
                        tool_calls.append({
                            "id": b.id,
                            "type": "function",
                            "function": {"name": b.name, "arguments": json.dumps(b.input)},
                        })
                msg = {"role": "assistant", "content": " ".join(text_parts) or None}
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                out.append(msg)
                continue

            # user tool_result blocks
            if role == "user":
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        out.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": str(block.get("content", "")),
                        })
                continue

        out.append({"role": role, "content": str(content)})
    return out


class DeepSeekMessages:
    """Mimics anthropic.Anthropic().messages with DeepSeek under the hood."""

    def __init__(self, openai_client):
        self._client = openai_client

    def create(self, *, model: str, max_tokens: int, system: str,
               messages: list[dict], tools: list[dict] = None, **kwargs) -> _Response:
        oai_messages = [{"role": "system", "content": system}]
        oai_messages += _messages_to_openai(messages)

        call_kwargs: dict[str, Any] = {
            "model": "deepseek-chat",
            "max_tokens": max_tokens,
            "messages": oai_messages,
        }
        if tools:
            call_kwargs["tools"] = _anthropic_tools_to_openai(tools)
            call_kwargs["tool_choice"] = "auto"

        resp = self._client.chat.completions.create(**call_kwargs)
        choice = resp.choices[0]
        msg = choice.message

        content_blocks: list[_ContentBlock] = []
        stop_reason = "end_turn"

        if msg.tool_calls:
            stop_reason = "tool_use"
            if msg.content:
                content_blocks.append(_ContentBlock("text", text=msg.content))
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                content_blocks.append(_ContentBlock(
                    "tool_use",
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))
        else:
            content_blocks.append(_ContentBlock("text", text=msg.content or ""))

        usage = _Usage(
            inp=getattr(resp.usage, "prompt_tokens", 0),
            out=getattr(resp.usage, "completion_tokens", 0),
        )
        return _Response(content_blocks, stop_reason, usage)


class DeepSeekAnthropic:
    """Drop-in replacement for anthropic.Anthropic() using DeepSeek."""

    def __init__(self, api_key: str):
        from openai import OpenAI
        _client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.messages = DeepSeekMessages(_client)
