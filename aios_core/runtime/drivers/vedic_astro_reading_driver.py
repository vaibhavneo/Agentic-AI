"""
Reference driver for the vedic_astro_reading skill (v1.0.0).

HTTP wrapper around vedic_astro/'s already-running server (D20: vedic_astro
owns an `agents/` package that collides with brain/'s bare top-level import
name, confirmed empirically — HTTP avoids importing it into the
orchestrator's process at all). Implements the app's own 2-step
geocode->reading sequence as driver-internal glue (H-O4: one skill, not two)
by calling vedic_astro/'s own /api/geocode then /api/reading/stream
endpoints directly, in the app's own ordering — never reimplementing its
chart math. No model or vendor is named here; vedic_astro makes its own LLM
calls internally, invisible to this driver.
"""
from __future__ import annotations

import os

import requests

from aios_core.runtime.drivers._sse_client import post_sse

DEFAULT_BASE_URL = "http://localhost:5050"


def _base_url(context: dict) -> str:
    return context.get("vedic_astro_url") or os.environ.get(
        "VEDIC_ASTRO_URL", DEFAULT_BASE_URL)


def run(inputs: dict, context: dict) -> dict:
    context = context or {}
    place, date, time_str = inputs["place"], inputs["date"], inputs["time"]
    base = _base_url(context)

    # Test seam: a caller may inject stubs to stay hermetic (no network).
    geocoder = context.get("_geocode_post", _default_json_post)
    reader = context.get("_reading_sse", post_sse)

    # ── Step 1: GEOCODE ───────────────────────────────────────────────────
    geo_status, geo = geocoder(f"{base}/api/geocode", {"place": place})
    if geo_status >= 400 or "error" in (geo or {}):
        detail = (geo or {}).get("error", f"HTTP {geo_status}")
        raise RuntimeError(f"vedic_astro geocode failed: {detail}")

    birth_info = {
        "date": date, "time": time_str, "place": place,
        "lat": geo["lat"], "lon": geo["lon"],
        "tz_offset": geo.get("timezone_offset_hours", 0.0),
    }

    # ── Step 2: READING (SSE) ─────────────────────────────────────────────
    sections: dict[str, dict] = {}
    saw_done = False
    saw_error = None
    for event, data in reader(f"{base}/api/reading/stream", {"birth_info": birth_info}):
        if event == "section":
            sections[data["key"]] = {"title": data.get("title", ""),
                                     "content": data.get("content", "")}
        elif event == "error":
            saw_error = data
            break
        elif event == "done":
            saw_done = True
            break

    if saw_error is not None:
        raise RuntimeError(f"vedic_astro reading failed: {saw_error}")
    if not saw_done:
        raise RuntimeError("vedic_astro reading stream ended without a 'done' event")
    if not sections:
        raise RuntimeError("vedic_astro reading stream produced no sections")

    return {"app": "vedic_astro", "birth_info": birth_info, "sections": sections}


def _default_json_post(url, payload):
    resp = requests.post(url, json=payload, timeout=30)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return resp.status_code, data
