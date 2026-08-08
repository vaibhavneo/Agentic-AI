"""HealthPilot's aios_core integration seam (PoC retrofit).

HTTP wrapper around HealthPilot's own already-running Flask server —
mirrors aios_core/runtime/drivers/vedic_astro_reading_driver.py and
health_agent_analyze_driver.py exactly, for the same reason (D20):
HealthPilot owns a bare top-level `agents/` package (agents.orchestrator,
agents.specialists, ...) that would collide with the orchestrator process's
own import namespace if imported directly — confirmed by inspecting
healthpilot/agents/*.py's own bare `from agents.X import Y` style before
writing this file. HTTP avoids ever importing HealthPilot code into
aios_core's process.

This is also HealthPilot's ONE file that plugs a reasoning path into
aios_core's `agent` seam (aios_core/sdk/agent.py) — no runtime/skill code
elsewhere names a model or calls out to HealthPilot's HTTP API directly.
The actual LLM call still happens exactly where it always did, inside
HealthPilot's own process (agents/orchestrator.py + agents/llm_client.py,
both UNCHANGED by this retrofit except for the additive
specialist_override/model_override parameters) — this file only decides
*which* HealthPilot specialist/model a given aios_core dispatch asks for,
via the HTTP request body. Swapping the backing model is therefore just a
different `model` value in that body, never a code change to
orchestrator.py's control flow or prompts (PROJECT_CHARTER.md P8).
"""
from __future__ import annotations

import os

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:3000"

# aios_core skill id -> HealthPilot's own internal specialist key
# (agents/specialists.py::SPECIALISTS). Kept as an explicit table rather than
# string-stripping the "healthpilot_" prefix so a naming drift on either side
# fails loudly (KeyError) instead of silently mis-routing.
SKILL_ID_TO_SPECIALIST = {
    "healthpilot_nutrition_planner": "nutrition_planner",
    "healthpilot_food_logging_agent": "food_logging_agent",
    "healthpilot_heart_health_agent": "heart_health_agent",
    "healthpilot_fitness_agent": "fitness_agent",
    "healthpilot_vitals_agent": "vitals_agent",
    "healthpilot_health_pattern_analyst": "health_pattern_analyst",
    "healthpilot_general_coach": "general",
}


def _base_url(context: dict) -> str:
    return context.get("healthpilot_url") or os.environ.get(
        "HEALTHPILOT_URL", DEFAULT_BASE_URL)


def make_adapter(post_json=None):
    """Returns agent_adapter(manifest, inputs, context) -> output, per
    aios_core/sdk/agent.py's contract. `post_json(url, payload) -> (status,
    body)` is injectable for hermetic tests (no real HTTP/socket) — default
    posts for real via `requests`, same test-seam shape as
    vedic_astro_reading_driver.py / health_agent_analyze_driver.py."""
    poster = post_json or _default_post

    def adapter(manifest: dict, inputs: dict, context: dict) -> dict:
        context = context or {}
        specialist_key = SKILL_ID_TO_SPECIALIST.get(manifest["id"])
        if specialist_key is None:
            raise ValueError(f"no specialist mapping for skill id '{manifest['id']}'")

        base = _base_url(context)
        profile_id = inputs["profile_id"]
        payload = {
            "message": inputs["message"],
            "history": inputs.get("history"),
            "specialist": specialist_key,
        }
        if inputs.get("model"):
            payload["model"] = inputs["model"]

        status, data = poster(f"{base}/api/profiles/{profile_id}/coach/ask", payload)
        if status >= 400 or "error" in (data or {}):
            detail = (data or {}).get("error", f"HTTP {status}")
            raise RuntimeError(f"healthpilot coach/ask returned an error: {detail}")

        return {
            "answer": data["answer"],
            "data_used": data.get("data_used", []),
            "ai_used": bool(data.get("ai_used", False)),
            "specialist": data.get("specialist", specialist_key),
        }

    return adapter


def _default_post(url, payload):
    resp = requests.post(url, json=payload, timeout=60)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return resp.status_code, data
