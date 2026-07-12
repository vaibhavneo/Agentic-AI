"""
Shared minimal SSE client for wrapper-skill drivers that reach an app over
HTTP (D20: apps whose bare top-level module names collide with brain's
internals go over HTTP, never in-process). Not a skill itself — a plain
helper, no manifest, no model, no vendor.
"""
from __future__ import annotations

import json
from typing import Iterable

import requests


def post_sse(url: str, payload: dict, timeout: float = 120.0):
    """POST an SSE request; yield (event_name, data_dict) pairs as they arrive.
    `event_name` defaults to 'message' per the SSE spec when a stream omits
    an explicit `event:` line."""
    with requests.post(url, json=payload, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        event = "message"
        for raw in resp.iter_lines(decode_unicode=True):
            if raw is None or raw == "":
                continue
            if raw.startswith("event:"):
                event = raw[len("event:"):].strip()
            elif raw.startswith("data:"):
                data = raw[len("data:"):].strip()
                try:
                    yield event, json.loads(data)
                except json.JSONDecodeError:
                    yield event, {"raw": data}
                event = "message"


def collect_sse(url: str, payload: dict, terminal_events: Iterable[str],
                 timeout: float = 120.0) -> dict:
    """Consume an SSE stream fully; return {event_name: [data, ...]} grouped by
    event name. Stops at the first event in `terminal_events` (inclusive)."""
    terminal = set(terminal_events)
    grouped: dict[str, list] = {}
    for event, data in post_sse(url, payload, timeout=timeout):
        grouped.setdefault(event, []).append(data)
        if event in terminal:
            break
    return grouped
