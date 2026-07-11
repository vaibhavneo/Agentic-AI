"""
Domain Pack loader / manager.

A Domain Pack is a self-contained folder that adds skills, workflows, corpora,
mission templates, evaluation rules and memory extensions for one knowledge
domain — WITHOUT modifying AIOS Core. Packs plug in only through documented
core interfaces:

  - skills   → a composite `Registry` (core skills + pack skills merged in
               memory); dispatched via the core dispatcher's `registry=` param.
  - corpora  → `aios_core.retrieval.register_corpus` (idempotent; skips existing).
  - missions → `aios_core.mission` templates.
  - workflows→ `aios_core.workflow.run(..., registry=composite)`.

No core code is changed. See DOMAIN_PACKS.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aios_core import retrieval, mission                       # noqa: E402
from aios_core.runtime.registry import Registry                # noqa: E402
from aios_core.runtime.dispatcher import dispatch, run_workflow  # noqa: E402

PACKS_DIR = Path(__file__).resolve().parent

# The pack descriptor is JSON, not YAML — consistency with decision D13
# (one machine format, stdlib json, no new dependency). See DOMAIN_PACKS.md §2.
PACK_MANIFEST = "pack.json"

_REQUIRED_PACK_KEYS = {"id", "name", "version", "description", "domain",
                       "aios_core_compat", "skills", "corpora",
                       "workflows", "mission_templates", "retrieval"}


class PackManager:
    """Discovers and loads domain packs into a composite registry. Stateless
    with respect to the core: the core is never mutated; a fresh composite
    Registry is built per manager instance."""

    def __init__(self, packs_dir: Path = PACKS_DIR):
        self.packs_dir = Path(packs_dir)
        self.loaded: dict[str, dict] = {}          # pack_id -> descriptor
        self._registry = Registry()                # core skills (11)

    # ── discovery ──────────────────────────────────────────────────────────
    def discover(self) -> list[str]:
        return sorted(p.parent.name for p in self.packs_dir.glob(f"*/{PACK_MANIFEST}"))

    def read_descriptor(self, pack_id: str) -> dict:
        mf = self.packs_dir / pack_id / PACK_MANIFEST
        if not mf.exists():
            raise KeyError(f"no pack '{pack_id}' ({mf} missing)")
        return json.loads(mf.read_text())

    # ── loading ──────────────────────────────────────────────────────────────
    def load(self, pack_id: str, ingest_corpora: bool = False) -> dict:
        """Load one pack: merge its skills into the composite registry and
        (idempotently) register its declared corpora. Returns the descriptor."""
        d = self.read_descriptor(pack_id)
        pack_dir = self.packs_dir / pack_id

        # 1. Skills → composite registry (inline manifests; no SKILLS_DIR needed)
        for s in d.get("skills", []):
            entry = self._skill_entry(pack_dir, s)
            self._registry.register(entry)          # in-memory federation

        # 2. Corpora the pack PROVIDES → corpus registry (idempotent).
        #    `corpora` lists corpus ids the pack USES (must already resolve);
        #    `provides_corpora` are new inline corpora this pack registers.
        existing = {c["id"] for c in retrieval.list_corpora()}
        for c in d.get("provides_corpora", []):
            if c["id"] not in existing:
                retrieval.register_corpus(c)
                if ingest_corpora:
                    retrieval.ingest_corpus(c["id"])

        self.loaded[pack_id] = d
        return d

    def load_all(self, ingest_corpora: bool = False) -> list[str]:
        for pid in self.discover():
            self.load(pid, ingest_corpora=ingest_corpora)
        return list(self.loaded)

    # ── the composite runtime surface (core, extended) ───────────────────────
    def registry(self) -> Registry:
        return self._registry

    def run_skill(self, skill_id: str, inputs: dict, context: dict | None = None,
                  version: str = "*"):
        """Dispatch a skill (core OR pack) through the UNMODIFIED core dispatcher,
        injecting the composite registry."""
        return dispatch(skill_id, inputs, context or {},
                        registry=self._registry, version_constraint=version)

    def run_workflow(self, workflow: dict, context: dict | None = None):
        return run_workflow(workflow, context or {}, registry=self._registry)

    def load_workflow(self, pack_id: str, name: str) -> dict:
        return json.loads((self.packs_dir / pack_id / "workflows" / name).read_text())

    # ── mission templates ────────────────────────────────────────────────────
    def mission_templates(self, pack_id: str | None = None) -> dict:
        out = {}
        for pid, d in self.loaded.items():
            if pack_id and pid != pack_id:
                continue
            for t in d.get("mission_templates", []):
                out[f"{pid}:{t['id']}"] = {**t, "pack": pid}
        return out

    def instantiate_template(self, template_key: str, store: mission.MissionStore | None = None,
                             title: str | None = None) -> dict:
        """Create a real mission from a pack template via the Mission SDK."""
        t = self.mission_templates().get(template_key)
        if not t:
            raise KeyError(f"no template '{template_key}'")
        store = store or mission.default_store
        return store.create(title or t["title"], t.get("type", "learn"), t["goal"],
                            corpora=t["corpora"], cross_corpus=t.get("cross_corpus", False),
                            tasks=t.get("tasks"))

    # ── conformance (validation) ─────────────────────────────────────────────
    def conformance(self, pack_id: str) -> dict:
        """Deterministic pack-contract check (PROJECT_CHARTER.md P6: evaluator
        before trust). Verifies required keys, skill manifests validate, and
        workflows reference only known skills."""
        issues: list[str] = []
        try:
            d = self.read_descriptor(pack_id)
        except KeyError as e:
            return {"ok": False, "issues": [str(e)]}
        pack_dir = self.packs_dir / pack_id

        missing = _REQUIRED_PACK_KEYS - set(d)
        if missing:
            issues.append(f"pack.json missing keys: {sorted(missing)}")
        if not str(d.get("version", "")).count(".") == 2:
            issues.append(f"version not semver: {d.get('version')}")

        reg = Registry()
        skill_ids = set()
        for s in d.get("skills", []):
            try:
                entry = self._skill_entry(pack_dir, s)
                reg.register(entry)                 # validates manifest completeness
                skill_ids.add(entry["id"])
            except Exception as e:
                issues.append(f"skill '{s}': {e}")
        known = set(reg.list_ids())
        for wf_name in d.get("workflows", []):
            wf_path = pack_dir / "workflows" / wf_name
            if not wf_path.exists():
                issues.append(f"workflow file missing: {wf_name}"); continue
            wf = json.loads(wf_path.read_text())
            for step in wf.get("steps", []):
                if step["skill"] not in known:
                    issues.append(f"workflow '{wf_name}' step references unknown skill '{step['skill']}'")
        for req in ("evaluation.md", "README.md"):
            if not (pack_dir / req).exists():
                issues.append(f"missing {req}")
        for t in d.get("mission_templates", []):
            if not t.get("corpora"):
                issues.append(f"template '{t.get('id')}' declares no corpora (P9)")
        # corpora the pack USES must resolve (either already-registered or provided)
        available = {c["id"] for c in retrieval.list_corpora()} | \
                    {c["id"] for c in d.get("provides_corpora", [])}
        for cid in d.get("corpora", []):
            if cid not in available:
                issues.append(f"declared corpus '{cid}' does not resolve")
        return {"ok": not issues, "issues": issues, "skills": sorted(skill_ids)}

    # ── internals ────────────────────────────────────────────────────────────
    def _skill_entry(self, pack_dir: Path, s) -> dict:
        """Normalize a pack skill spec into a registry entry with an INLINE
        manifest (so it needs no SKILLS_DIR resolution)."""
        if isinstance(s, dict) and "manifest" in s:
            return {"id": s["id"], "version": s.get("version", s["manifest"]["version"]),
                    "manifest": s["manifest"]}
        # else: a path (str) or {id, manifest_path}
        mp = s if isinstance(s, str) else s["manifest_path"]
        manifest = json.loads((pack_dir / mp).read_text())
        return {"id": manifest["id"], "version": manifest["version"], "manifest": manifest}
