"""
AIOS Core SDK — Agent API (stable).

Agents are skills + reasoning adapters. Deterministic skills need no adapter;
generative (agent-type) skills require one. The runtime never embeds a model —
adapters are the ONLY seam through which a model (or human, or program) enters
(PROJECT_CHARTER.md P8). This API manages adapters and runs agent skills.

    from aios_core import agent
    agent.register_adapter("teacher", my_llm_fn)
    result = agent.run("hypothesis_generation", inputs, adapter=my_llm_fn)
"""
from __future__ import annotations

from ..runtime.dispatcher import dispatch
from ..runtime.registry import Registry
from ..runtime.lifecycle import DispatchResult

__all__ = ["register_adapter", "get_adapter", "list_agent_skills",
           "run", "make_context"]

# Named adapter registry (process-local). Adapters are callables:
#   agent_adapter(manifest: dict, inputs: dict, context: dict) -> output dict
#   task_executor(inputs: dict, root: Path, cycle: int) -> cycle-result dict
_ADAPTERS: dict[str, callable] = {}


def register_adapter(name: str, fn) -> None:
    _ADAPTERS[name] = fn


def get_adapter(name: str):
    return _ADAPTERS.get(name)


def list_agent_skills(registry: Registry | None = None) -> list[str]:
    """Skill ids whose runtime type is 'agent' (require an adapter to execute)."""
    reg = registry or Registry()
    out = []
    for sid in reg.list_ids():
        m = reg.get_manifest(sid)
        if m["execution"].get("runtime", {}).get("type") == "agent":
            out.append(sid)
    return out


def make_context(agent_adapter=None, task_executor=None, **extra) -> dict:
    """Build a dispatch context wiring reasoning callables in the canonical keys."""
    ctx = dict(extra)
    if agent_adapter is not None:
        ctx["agent_adapter"] = agent_adapter
    if task_executor is not None:
        ctx["task_executor"] = task_executor
    return ctx


def run(skill_id: str, inputs: dict, adapter=None, adapter_name: str | None = None,
        version: str = "*") -> DispatchResult:
    """Run an agent-type skill with a reasoning adapter. `adapter` is a callable;
    `adapter_name` looks one up from the registry. Output is still schema-
    validated by the runtime — a weak adapter cannot silently break the contract."""
    fn = adapter or (get_adapter(adapter_name) if adapter_name else None)
    return dispatch(skill_id, inputs, make_context(agent_adapter=fn),
                    version_constraint=version)
