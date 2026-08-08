"""Append-only log of safety-relevant decisions, for audit + testing."""
from __future__ import annotations

import json

from database.db import get_connection


def log_safety_event(profile_id: str, event_type: str, severity: str, message: str, context: dict | None = None) -> int:
    if severity not in ("info", "warning", "urgent"):
        raise ValueError(f"invalid severity: {severity}")
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO safety_events (profile_id, event_type, severity, message, context_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (profile_id, event_type, severity, message, json.dumps(context or {})),
    )
    conn.commit()
    return cur.lastrowid


def list_safety_events(profile_id: str, limit: int = 100) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM safety_events WHERE profile_id = ? ORDER BY created_at DESC LIMIT ?",
        (profile_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
