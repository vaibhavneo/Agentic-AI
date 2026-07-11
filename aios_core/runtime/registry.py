"""
Skill Runtime — Registry.
Registration, discovery, version lookup, dependency resolution (topological),
and semver compatibility checks over brain/skills/registry.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import os
# AIOS Core is the engine; the SKILL LIBRARY is content loaded from a configured
# location. Default = in-repo library at brain/skills/ (unmoved — only the
# runtime relocated). Override with AIOS_SKILLS_DIR.
_ROOT = Path(__file__).resolve().parents[2]          # aios_core/runtime -> repo root
SKILLS_DIR = Path(os.environ.get("AIOS_SKILLS_DIR", _ROOT / "brain" / "skills"))
REGISTRY_PATH = SKILLS_DIR / "registry.json"

_MANIFEST_REQUIRED = {"id", "name", "version", "description", "inputs",
                      "outputs", "memory", "execution", "dependencies",
                      "evaluation", "tags"}


def _parse_ver(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", v.strip())
    if not m:
        raise ValueError(f"bad semver: {v}")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def satisfies(version: str, constraint: str) -> bool:
    """Constraint grammar: '>=X.Y.Z <A.B.C' (space-separated), '=X.Y.Z', or '*'."""
    if constraint.strip() in ("*", ""):
        return True
    v = _parse_ver(version)
    for part in constraint.split():
        if part.startswith(">="):
            if not v >= _parse_ver(part[2:]): return False
        elif part.startswith("<="):
            if not v <= _parse_ver(part[2:]): return False
        elif part.startswith("<"):
            if not v < _parse_ver(part[1:]): return False
        elif part.startswith(">"):
            if not v > _parse_ver(part[1:]): return False
        elif part.startswith("="):
            if not v == _parse_ver(part[1:]): return False
        else:
            if not v == _parse_ver(part): return False
    return True


class Registry:
    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {"skills": []}
        self._entries: dict[str, dict] = {e["id"]: e for e in data.get("skills", [])}

    # ── registration ──────────────────────────────────────────────────────
    def register(self, entry: dict, persist: bool = False) -> None:
        """entry = {id, version, manifest | manifest_path}. Validates manifest."""
        m = self._resolve_manifest(entry)
        missing = _MANIFEST_REQUIRED - set(m.keys())
        if missing:
            raise ValueError(f"manifest incomplete for '{entry.get('id')}': missing {sorted(missing)}")
        self._entries[entry["id"]] = entry
        if persist:
            self.path.write_text(json.dumps(
                {"registry_version": "1.0.0",
                 "skills": list(self._entries.values())}, indent=1))

    # ── discovery ─────────────────────────────────────────────────────────
    def list_ids(self) -> list[str]:
        return sorted(self._entries)

    def discover(self, query: str = "", tag: str = "") -> list[dict]:
        out = []
        for e in self._entries.values():
            m = self._resolve_manifest(e)
            if tag and tag not in m.get("tags", []):
                continue
            hay = f"{m['id']} {m['name']} {m['description']}".lower()
            if query.lower() in hay:
                out.append({"id": m["id"], "version": m["version"],
                            "description": m["description"], "tags": m["tags"]})
        return out

    # ── lookup ────────────────────────────────────────────────────────────
    def get_manifest(self, skill_id: str, constraint: str = "*") -> dict:
        e = self._entries.get(skill_id)
        if not e:
            raise KeyError(f"skill not found: {skill_id}")
        m = self._resolve_manifest(e)
        if not satisfies(m["version"], constraint):
            raise ValueError(
                f"incompatible: {skill_id} v{m['version']} does not satisfy '{constraint}'")
        return m

    # ── dependency resolution ─────────────────────────────────────────────
    def resolve_dependencies(self, skill_id: str, include_optional: bool = False) -> list[str]:
        """Topological order (dependencies first), cycle-safe."""
        order: list[str] = []
        visiting: set[str] = set()

        def visit(sid: str, constraint: str = "*"):
            if sid in order:
                return
            if sid in visiting:
                raise ValueError(f"dependency cycle at '{sid}'")
            visiting.add(sid)
            m = self.get_manifest(sid, constraint)   # raises on missing/incompatible
            for dep in m.get("dependencies", []):
                if dep.get("optional") and not include_optional:
                    continue
                visit(dep["id"], dep.get("version", "*"))
            visiting.discard(sid)
            order.append(sid)

        visit(skill_id)
        return order

    # ── internals ─────────────────────────────────────────────────────────
    def _resolve_manifest(self, entry: dict) -> dict:
        if "manifest" in entry:
            return entry["manifest"]
        return json.loads((SKILLS_DIR / entry["manifest_path"]).read_text())
