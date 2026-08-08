"""Health Orchestrator: routes a question to a specialist (agents/router.py)
then runs a real tool-calling loop against DeepSeek/OpenAI-compatible
function calling. Falls back to agents/fallback_coach.py — still
tool-grounded, just not conversational — if no AI provider is configured or
the AI call fails outright, so the Coach never goes fully decorative.
"""
from __future__ import annotations

import json

from app import config
from agents.fallback_coach import answer_without_ai
from agents.llm_client import get_client
from agents.router import route_question
from agents.specialists import SAFETY_PREAMBLE, SPECIALISTS
from agents.tool_registry import execute_tool
from agents.tool_specs import build_tool_specs

MAX_TOOL_ITERATIONS = 5


def _run_openai_style_loop(client, model: str, specialist_key: str, profile_id: str, message: str, history: list[dict] | None) -> tuple[str, list[dict]]:
    spec = SPECIALISTS[specialist_key]
    system_prompt = SAFETY_PREAMBLE + "\n\n" + spec["system_prompt"]
    tool_specs = build_tool_specs(spec["tools"])

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    data_used = []
    for _ in range(MAX_TOOL_ITERATIONS):
        kwargs = dict(model=model, messages=messages, max_tokens=1200, extra_body={"thinking": {"type": "disabled"}})
        if tool_specs:
            kwargs["tools"] = tool_specs
        resp = client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        if not getattr(msg, "tool_calls", None):
            return msg.content or "", data_used

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if name not in spec["tools"]:
                result = {"error": f"tool '{name}' is not available to the {specialist_key} specialist"}
            else:
                result = execute_tool(name, profile_id, args)
            data_used.append({"tool": name, "arguments": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)})

    return (
        "I looked at several data points but couldn't finish forming an answer within my tool-call budget — "
        "try asking a more specific question.",
        data_used,
    )


def answer_question(profile_id: str, message: str, history: list[dict] | None = None) -> dict:
    if not config.ai_configured():
        return answer_without_ai(profile_id, message)

    try:
        client, provider = get_client()
    except RuntimeError:
        return answer_without_ai(profile_id, message)

    specialist_key = route_question(message)

    try:
        if provider == "deepseek":
            answer_text, data_used = _run_openai_style_loop(client, config.DEEPSEEK_MODEL, specialist_key, profile_id, message, history)
        else:
            # Anthropic fallback provider — no tool loop implemented; answer
            # from the specialist's system prompt plus a couple of
            # deterministic tool calls surfaced as context, no free tool use.
            fallback = answer_without_ai(profile_id, message)
            return fallback
    except Exception:
        return answer_without_ai(profile_id, message)

    return {
        "answer": answer_text,
        "specialist": specialist_key,
        "specialist_label": SPECIALISTS[specialist_key]["label"],
        "data_used": data_used,
        "ai_used": True,
    }
