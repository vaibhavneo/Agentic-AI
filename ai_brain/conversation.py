"""
Session/conversation persistence for the main /api/ask chat.

Ports vedic_astro's conversations.py pattern (JSON-file-backed, trimmed
message list) but simplified: AI Brain is explicitly single-reader, no
login (mastery.py's own docstring: "one reader, no login, nothing else in
this app has that concept either"), so there is no per-id derivation here —
just one ongoing conversation, resettable via reset_conversation().

Before this module, pipeline.py::run() had no memory of prior turns at all,
and web/index.html sent nothing but the bare question on every request — a
follow-up like "why?" or "tell me more" was answered with zero context
about what was just discussed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

CONVERSATION_PATH = Path(__file__).parent / "memory" / "conversation.json"
MAX_STORED_TURNS = 10   # 20 messages — deliberately small; see pipeline.py's
                        # history-injection comment for why (DeepSeek can burn
                        # a tight token budget entirely on reasoning, so this
                        # module keeps the payload it hands back small on
                        # purpose rather than trusting the caller to trim it).


def load_conversation() -> dict:
    if not CONVERSATION_PATH.exists():
        return {}
    try:
        return json.loads(CONVERSATION_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(messages: list[dict]) -> None:
    CONVERSATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = load_conversation()
    payload = {
        "messages": messages,
        "created_at": existing.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    CONVERSATION_PATH.write_text(json.dumps(payload, indent=2))


def append_turn(question: str, answer: str) -> list[dict]:
    """Loads existing history, appends the new user/assistant turn, persists,
    and returns the updated (already-trimmed) message list."""
    existing = load_conversation()
    messages = list(existing.get("messages", []))
    messages.append({"role": "user", "content": question})
    messages.append({"role": "assistant", "content": answer})
    messages = messages[-(MAX_STORED_TURNS * 2):]
    _save(messages)
    return messages


def reset_conversation() -> None:
    if CONVERSATION_PATH.exists():
        CONVERSATION_PATH.unlink()
