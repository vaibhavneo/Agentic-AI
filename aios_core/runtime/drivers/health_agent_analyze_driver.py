"""
Reference driver for the health_agent_analyze skill (v1.0.0).

HTTP wrapper around health-agent/'s already-running server (D20:
health-agent owns `agents/` and `tools/` packages that collide with brain/'s
bare top-level import names, confirmed empirically — HTTP avoids importing
it into the orchestrator's process at all). Calls the plain-JSON
`/analyze/text` endpoint (free-text vitals, e.g. "HR=88 BP=145/92 SpO2=94").
No model or vendor is named here; health-agent makes its own LLM calls
internally, invisible to this driver.
"""
from __future__ import annotations

import os

import requests

DEFAULT_URL = "http://localhost:8787/analyze/text"


def run(inputs: dict, context: dict) -> dict:
    context = context or {}
    text = inputs["text"]
    url = context.get("health_agent_url") or os.environ.get(
        "HEALTH_AGENT_URL", DEFAULT_URL)

    # Test seam: inject a stub poster to stay hermetic (no network).
    poster = context.get("_http_post", _default_post)
    status, data = poster(url, {"text": text})

    if status >= 400 or "error" in (data or {}):
        detail = (data or {}).get("error", f"HTTP {status}")
        raise RuntimeError(f"health-agent returned an error: {detail}")

    return {"app": "health_agent", "result": data}


def _default_post(url, payload):
    resp = requests.post(url, json=payload, timeout=60)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return resp.status_code, data
