"""
Reference driver for the feynman_ask skill (v1.0.0).

Thin in-process pass-through to feynman_agent/'s Feynman-technique QM tutor
(get_session(session_id).ask(question)). feynman_agent/ is the ONLY app
besides brain/ that D20 confirmed safe to import in-process: its only bare
top-level module is `agent` (singular), which does not collide with
brain/agents/ or brain/tools/. No model or vendor is named here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_FEYNMAN_DIR = _ROOT / "feynman_agent"


def _get_session_fn():
    if str(_FEYNMAN_DIR) not in sys.path:
        sys.path.insert(0, str(_FEYNMAN_DIR))
    from agent import get_session
    return get_session


def run(inputs: dict, context: dict) -> dict:
    context = context or {}
    question = inputs["question"]
    session_id = inputs.get("session_id", "default")

    # Test seam: inject a stub session to stay hermetic (no model, no network).
    session = context.get("_session_instance")
    if session is None:
        get_session = _get_session_fn()
        session = get_session(session_id)
    result = session.ask(question, session_id)
    return {
        "app": "feynman_agent",
        "answer": str(result.get("answer", "")),
        "sources": list(result.get("sources", [])),
        "chunks_retrieved": int(result.get("chunks_retrieved", 0)),
    }
