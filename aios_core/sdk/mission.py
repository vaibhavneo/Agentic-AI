"""
AIOS Core SDK — Mission API (stable).

A mission is a real project: a goal, declared corpora (scope), and a
recursive_planner-compatible memory root. Files are the source of truth;
SQLite is a rebuildable mirror (PROJECT_CHARTER.md P2). Extracted from the
learn_agent app so ANY application can host missions (requirement #1, #5).

    from aios_core import mission
    m = mission.create("Learn RL", "learn", "explain 3 RL algos",
                       corpora=["ai-books"], tasks=["read ch1", "impl q-learning", "eval"])
    m = mission.get(m["id"]); missions = mission.list_all()
    job = mission.run(m["id"], stability_criteria=[...])   # background loop
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from second_brain import corpus_manager as _cm          # noqa: E402
from .workflow import BackgroundRun                      # noqa: E402

__all__ = ["MissionStore", "create", "get", "list_all", "set_corpora",
           "run", "default_store"]

_STATE_TMPL = """# state.md — {title}
## Meta
- goal: {goal}
- status: active
- loop_iteration: 0
- last_updated: {today}
## Stability Criteria
{criteria}
"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS missions(
  id TEXT PRIMARY KEY, title TEXT, type TEXT, goal TEXT, status TEXT,
  memory_root TEXT, cross_corpus INTEGER, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS mission_corpora(mission_id TEXT, corpus_id TEXT);
"""


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]


class MissionStore:
    """Files-first mission store with a SQLite mirror. Locations are
    configurable so different apps can host their own mission spaces; defaults
    match the historical AIOS locations for backward compatibility."""

    def __init__(self, missions_dir=None, db_path=None):
        self.missions_dir = Path(missions_dir or _ROOT / "memory" / "missions")
        self.db_path = Path(db_path or _ROOT / "learn_agent" / "data" / "aios.db")

    def _db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def create(self, title, mtype, goal, corpora, cross_corpus=False, tasks=None):
        if not corpora:
            raise ValueError("a mission must declare at least one corpus")
        for cid in corpora:
            _cm.get(cid)                     # raises on unknown corpus (P9)
        slug = _slugify(title)
        root = self.missions_dir / slug
        if (root / "mission.json").exists():
            raise ValueError(f"mission exists: {slug}")
        root.mkdir(parents=True, exist_ok=True)

        mission = {"id": slug, "title": title, "type": mtype, "goal": goal,
                   "corpora": corpora, "cross_corpus": cross_corpus,
                   "status": "active", "created": date.today().isoformat()}
        (root / "mission.json").write_text(json.dumps(mission, indent=1))
        (root / "state.md").write_text(_STATE_TMPL.format(
            title=title, goal=goal, today=date.today().isoformat(),
            criteria="- [ ] goal reached (define checks in plan)"))
        task_lines = "\n".join(f"- [ ] {t}" for t in
                               (tasks or ["define first atomic task"]))
        (root / "plan.md").write_text(
            f"# plan.md\n## Objective\n{goal}\n\n## Tasks\n{task_lines}\n")
        for fn, hdr in [("log.md", "# log.md\n"), ("decisions.md", "# decisions.md\n"),
                        ("notes.md", f"# notes — {title}\n"),
                        ("questions.md", "# open questions\n")]:
            (root / fn).write_text(hdr)

        conn = self._db()
        conn.execute("INSERT OR REPLACE INTO missions VALUES (?,?,?,?,?,?,?,?,?)",
                     (slug, title, mtype, goal, "active", str(root),
                      int(cross_corpus), mission["created"], mission["created"]))
        conn.execute("DELETE FROM mission_corpora WHERE mission_id=?", (slug,))
        for cid in corpora:
            conn.execute("INSERT INTO mission_corpora VALUES (?,?)", (slug, cid))
        conn.commit(); conn.close()
        return mission

    @staticmethod
    def _parse_tasks(root: Path) -> list[dict]:
        plan = root / "plan.md"
        if not plan.exists():
            return []
        out = []
        for i, line in enumerate(plan.read_text().splitlines()):
            m = re.match(r"- \[( |x)\] (.+)", line)
            if m:
                out.append({"id": i, "done": m.group(1) == "x",
                            "description": m.group(2)})
        return out

    def get(self, slug: str) -> dict:
        root = self.missions_dir / slug
        mf = root / "mission.json"
        if not mf.exists():
            raise KeyError(f"unknown mission: {slug}")
        m = json.loads(mf.read_text())
        tasks = self._parse_tasks(root)
        done = sum(1 for t in tasks if t["done"])
        m["tasks"] = tasks
        m["progress"] = round(100 * done / len(tasks)) if tasks else 0
        m["memory_files"] = sorted(f.name for f in root.glob("*.md"))
        qf = root / "questions.md"
        m["questions"] = ([ln[2:] for ln in qf.read_text().splitlines()
                           if ln.startswith("- ")] if qf.exists() else [])
        return m

    def list_all(self) -> list[dict]:
        out = []
        if self.missions_dir.exists():
            for mf in sorted(self.missions_dir.glob("*/mission.json")):
                try:
                    out.append(self.get(mf.parent.name))
                except Exception:
                    continue
        return out

    def set_corpora(self, slug, corpora=None, cross_corpus=None) -> dict:
        mf = self.missions_dir / slug / "mission.json"
        if not mf.exists():
            raise KeyError(f"unknown mission: {slug}")
        m = json.loads(mf.read_text())
        if corpora is not None:
            for cid in corpora:
                _cm.get(cid)
            m["corpora"] = corpora
        if cross_corpus is not None:
            m["cross_corpus"] = bool(cross_corpus)
        mf.write_text(json.dumps(m, indent=1))
        return m

    def run(self, slug, stability_criteria, max_cycles=10, context=None,
            job: BackgroundRun | None = None) -> BackgroundRun:
        """Execute a mission's recursive_planner loop in the background.
        Returns the BackgroundRun (poll .status())."""
        m = self.get(slug)
        inputs = {"goal": m["goal"], "memory_root": str(self.missions_dir / slug),
                  "stability_criteria": stability_criteria, "max_cycles": max_cycles}
        job = job or BackgroundRun()
        job.start_loop("recursive_planner", inputs, context, label=slug,
                       max_dispatches=max_cycles + 2)
        return job


# Module-level default store (backward-compatible locations) + thin functions.
default_store = MissionStore()


def create(title, mtype, goal, corpora, cross_corpus=False, tasks=None):
    return default_store.create(title, mtype, goal, corpora, cross_corpus, tasks)


def get(slug):
    return default_store.get(slug)


def list_all():
    return default_store.list_all()


def set_corpora(slug, corpora=None, cross_corpus=None):
    return default_store.set_corpora(slug, corpora, cross_corpus)


def run(slug, stability_criteria, max_cycles=10, context=None, job=None):
    return default_store.run(slug, stability_criteria, max_cycles, context, job)
