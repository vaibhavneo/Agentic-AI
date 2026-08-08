"""Thin DeepSeek/Anthropic client wrapper shared by the NL logging pipeline
(M2) and the specialist agents (M6). The LLM is only ever used here to (a)
interpret already-computed structured results into prose, or (b) parse free
text into candidate structures for deterministic code to resolve — never to
do arithmetic or invent a nutrition/health value. See safety/ for the
enforcement layer that keeps it that way.
"""
from __future__ import annotations

import json

from app import config

_client = None
_provider = None


def get_client():
    global _client, _provider
    if _client is not None:
        return _client, _provider

    if config.DEEPSEEK_API_KEY:
        from openai import OpenAI
        _client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        _provider = "deepseek"
    elif config.ANTHROPIC_API_KEY:
        import anthropic
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        _provider = "anthropic"
    else:
        raise RuntimeError(
            "No AI provider configured. Set DEEPSEEK_API_KEY (or ANTHROPIC_API_KEY) in .env."
        )
    return _client, _provider


def chat_json(system: str, user: str, max_tokens: int = 1000) -> dict | list:
    """Calls the configured LLM and parses its response as JSON. Raises
    ValueError if the response isn't valid JSON — callers must handle that
    (typically by falling back to a deterministic heuristic) rather than
    trusting a malformed structure."""
    client, provider = get_client()

    if provider == "deepseek":
        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = resp.choices[0].message.content
    else:
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        content = resp.content[0].text

    if not content:
        raise ValueError("empty response from LLM")
    return json.loads(content)
