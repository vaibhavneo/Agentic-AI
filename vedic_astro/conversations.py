"""
Conversation memory (Phase 8). JSON-file-backed, one file per
conversation_id, mirroring persistence.py's chart-bundle storage pattern
(same path-traversal protections, same one-file-per-id isolation).

conversation_id is deterministically DERIVED from chart_id on the client
(and re-derivable on the server for validation) rather than being a new
piece of state the client has to separately persist: a chart_id of
"chart_<fp>" always maps to conversation_id "conv_<fp>". One chart therefore
always resumes the same conversation thread across reloads.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

CONVERSATIONS_DIR = Path(__file__).parent / "data" / "conversations"
MAX_STORED_MESSAGES = 40  # bound file size; oldest turns drop off first


def derive_conversation_id(chart_id: str) -> Optional[str]:
    """chart_<fp> -> conv_<fp>. Returns None if chart_id isn't well-formed."""
    if not chart_id or not isinstance(chart_id, str) or not chart_id.startswith("chart_"):
        return None
    return "conv_" + chart_id[len("chart_"):]


def _ensure_dir() -> None:
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_path(conversation_id: str) -> Optional[Path]:
    if not conversation_id or not isinstance(conversation_id, str):
        return None
    if "/" in conversation_id or "\\" in conversation_id or ".." in conversation_id:
        return None
    if not conversation_id.startswith("conv_"):
        return None
    return CONVERSATIONS_DIR / f"{conversation_id}.json"


def load_conversation(conversation_id: str) -> Optional[dict]:
    path = _safe_path(conversation_id)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_conversation(conversation_id: str, chart_id: str, messages: list[dict]) -> None:
    path = _safe_path(conversation_id)
    if path is None:
        raise ValueError("invalid conversation_id")
    _ensure_dir()
    trimmed = messages[-MAX_STORED_MESSAGES:]
    existing = load_conversation(conversation_id)
    payload = {
        "conversation_id": conversation_id,
        "chart_id": chart_id,
        "messages": trimmed,
        "created_at": (existing or {}).get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.write_text(json.dumps(payload, indent=2))


def append_turn(conversation_id: str, chart_id: str, question: str, answer: str) -> list[dict]:
    """Loads existing history for this conversation, appends the new
    user/assistant turn, persists, and returns the updated message list
    (already trimmed to MAX_STORED_MESSAGES)."""
    existing = load_conversation(conversation_id)
    messages = list((existing or {}).get("messages", []))
    messages.append({"role": "user", "content": question})
    messages.append({"role": "assistant", "content": answer})
    messages = messages[-MAX_STORED_MESSAGES:]
    save_conversation(conversation_id, chart_id, messages)
    return messages
