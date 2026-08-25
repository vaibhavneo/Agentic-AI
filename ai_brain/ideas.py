"""Idea memory: things the reader proposed or developed that are worth
remembering on their own — gated by pipeline.py's understand() classifying
the question as idea_worthy (a sibling boolean on its existing JSON
schema, not a new question_type value, so it never gets conflated with
mode selection). memory_spine.post_interaction_update() is the only
intended caller.

Same flat-JSON-file pattern as conversation.py/research.py, but a single
append-only list rather than paired turns or per-thread state — an idea is
a standalone thing worth recording, not part of a back-and-forth exchange.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

IDEAS_PATH = Path(__file__).parent / "memory" / "ideas.json"
MAX_STORED = 200   # a personal idea log, not an unbounded dump — oldest
                   # entries drop off once this is exceeded


def _load() -> list[dict]:
    try:
        return json.loads(IDEAS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _save(entries: list[dict]) -> None:
    try:
        IDEAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        IDEAS_PATH.write_text(json.dumps(entries, indent=1, ensure_ascii=False))
    except OSError:
        pass          # ideas are a convenience; never fail a run over it


def record(text: str, *, question: str = "", project: str = "") -> dict:
    """Append one idea. `question` is the reader's own original phrasing,
    kept for context later. `project` links it to a project name if one
    was inferred as relevant to this interaction — empty string otherwise,
    not None, so callers can always treat it as a string."""
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "text": text, "question": question, "project": project}
    entries = _load()
    entries.append(entry)
    entries = entries[-MAX_STORED:]
    _save(entries)
    return entry


def recent(n: int = 10) -> list[dict]:
    return _load()[-n:]


def all_ideas() -> list[dict]:
    return _load()


if __name__ == "__main__":
    for e in recent(20):
        tag = f" [{e['project']}]" if e.get("project") else ""
        print(f"  {e['at'][:10]}{tag}  {e['text'][:80]}")
