"""
Skill Runtime — Executor.
Runs a skill's execution contract via its declared runtime:
  - type "python": import entrypoint "pkg.module:function", call fn(inputs, context)
  - type "agent":  contract-card skill — executable ONLY if the caller supplies
                   an adapter callable in context["agent_adapter"]. The runtime
                   itself never embeds a model; adapters are how any LLM
                   (or human) plugs in. No adapter → typed NOT_EXECUTABLE.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]   # repo root, so aios_core.* imports resolve
_BRAIN = _ROOT / "brain"                       # legacy: runtime.drivers.* entrypoints


class NotExecutable(Exception):
    pass


def execute(manifest: dict, inputs: dict, context: dict) -> dict:
    rt = manifest["execution"].get("runtime", {"type": "agent"})
    if rt["type"] == "python":
        fn = _load_entrypoint(rt["entrypoint"])
        return fn(inputs, context)
    if rt["type"] == "agent":
        adapter = context.get("agent_adapter")
        if adapter is None:
            raise NotExecutable(
                f"skill '{manifest['id']}' is a contract-card (runtime=agent); "
                "supply context['agent_adapter'] = callable(manifest, inputs, context) -> output")
        return adapter(manifest, inputs, context)
    raise NotExecutable(f"unknown runtime type: {rt['type']}")


def _load_entrypoint(spec: str):
    mod_name, fn_name = spec.split(":")
    for _p in (_ROOT, _BRAIN):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    mod = importlib.import_module(mod_name)
    return getattr(mod, fn_name)
