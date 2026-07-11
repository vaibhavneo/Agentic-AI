"""
AIOS Core SDK — Skill API (stable).

The public way to discover and run skills. Applications import THIS, never the
runtime dispatcher/registry directly (PROJECT_CHARTER.md P10; requirement #3).

    from aios_core import skill
    result = skill.run("retrieve_context", {"query": "...", "corpora": ["ai-books"]})
    if result.ok: ...
"""
from __future__ import annotations

from ..runtime.dispatcher import dispatch
from ..runtime.registry import Registry, satisfies
from ..runtime.lifecycle import DispatchResult

__all__ = ["run", "list_skills", "get_manifest", "discover",
           "resolve_dependencies", "register", "satisfies", "DispatchResult"]


def run(skill_id: str, inputs: dict, context: dict | None = None,
        version: str = "*") -> DispatchResult:
    """Dispatch a skill through the full 9-step lifecycle. Never raises for
    skill-level failures — inspect result.ok / result.failure."""
    return dispatch(skill_id, inputs, context or {}, version_constraint=version)


def list_skills(registry: Registry | None = None) -> list[str]:
    return (registry or Registry()).list_ids()


def get_manifest(skill_id: str, version: str = "*",
                 registry: Registry | None = None) -> dict:
    return (registry or Registry()).get_manifest(skill_id, version)


def discover(query: str = "", tag: str = "",
             registry: Registry | None = None) -> list[dict]:
    return (registry or Registry()).discover(query=query, tag=tag)


def resolve_dependencies(skill_id: str, include_optional: bool = False,
                         registry: Registry | None = None) -> list[str]:
    return (registry or Registry()).resolve_dependencies(skill_id, include_optional)


def register(entry: dict, persist: bool = False,
             registry: Registry | None = None) -> None:
    (registry or Registry()).register(entry, persist=persist)
