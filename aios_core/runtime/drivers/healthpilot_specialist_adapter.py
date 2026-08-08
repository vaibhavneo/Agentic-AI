"""Loader for HealthPilot's agent_adapter (healthpilot/agents/aios_adapter.py).

HealthPilot's `agents/` package uses bare `from agents.X import Y` imports
internally (confirmed by inspection — same shape as vedic_astro and
health-agent, D20), so it can't be `sys.path`-inserted and imported as a
package here without risking exactly the collision those two apps' drivers
document. healthpilot/agents/aios_adapter.py itself has zero healthpilot-
internal imports (only stdlib + requests) specifically so it's safe to load
directly, but we still load it by file path via importlib — never touching
sys.path or the bare `agents` module name — so this stays true even if that
invariant ever drifts.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ADAPTER_PATH = Path(__file__).resolve().parents[3] / "healthpilot" / "agents" / "aios_adapter.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("healthpilot_aios_adapter", _ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_adapter(post_json=None):
    """Returns HealthPilot's agent_adapter(manifest, inputs, context) ->
    output. See healthpilot/agents/aios_adapter.py for the real logic —
    this file only loads it collision-safely."""
    return _load_module().make_adapter(post_json)
