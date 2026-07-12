"""
Reference driver for the brain_think skill (v1.0.0).

Thin in-process pass-through to brain/'s own multi-agent orchestrator
(Brain.think). Scoped sys.path insertion matches brain/cli.py's own pattern
exactly (D20 evidence) — bare `import brain` off the repo root resolves to
the directory as a namespace package, not brain/brain.py, so brain/ itself
must be on sys.path, not the repo root. No model or vendor is named here;
Brain.think makes its own model calls internally, unrelated to this seam.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_BRAIN_DIR = _ROOT / "brain"


def _brain_class():
    if str(_BRAIN_DIR) not in sys.path:
        sys.path.insert(0, str(_BRAIN_DIR))
    from brain import Brain
    return Brain


def run(inputs: dict, context: dict) -> dict:
    context = context or {}
    task = inputs["task"]
    auto_critique = bool(inputs.get("auto_critique", False))
    api_key = context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")

    # Test seam: a caller may inject a pre-built Brain instance to stay
    # hermetic (no network, no real model) — never used in production.
    brain_instance = context.get("_brain_instance")
    if brain_instance is None:
        Brain = _brain_class()
        brain_instance = Brain(api_key=api_key, verbose=False)
    answer = brain_instance.think(task, auto_critique=auto_critique)
    return {"app": "brain", "answer": str(answer)}
