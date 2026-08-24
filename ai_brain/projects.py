"""Projects: a cognitive context layer, not a project-management app.

A project is a named container the reader is actively working on (e.g. "Stock
AI Agent," "Vedic Astrology AI") that accumulates goals, questions, decisions
and notes over time, plus links to research threads or curriculum topics that
turned out to matter. It exists so a question like "what should my Stock AI
project learn from my agent-reliability research" has somewhere to look.

Same shape as research.py's notebook, deliberately: append-only entries (the
trail of what was decided when stays intact), a flat JSON file under memory/,
one `record()` entry point per field, a `brief()` that primes future context.
Kept intentionally small — four entry types plus one link, mirroring
research.py's own four types rather than the larger taxonomy this could grow
into later if real use ever needs it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import curriculum as CUR

PROJECTS_PATH = Path(__file__).parent / "memory" / "projects.json"


def _load() -> dict:
    try:
        return json.loads(PROJECTS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"projects": {}}


def _save(db: dict) -> None:
    try:
        PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROJECTS_PATH.write_text(json.dumps(db, indent=1, ensure_ascii=False))
    except OSError:
        pass          # projects are a convenience; never fail a run over it


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _retag(p: dict) -> None:
    """Recompute concept_tags from the accumulated goal text. Called only
    when a goal is recorded (goals define scope; notes/decisions/questions
    don't), so tagging is computed once per goal change and cached on the
    project — never recomputed per question, per the same discipline
    match_topics() itself already applies its score floor under."""
    text = " ".join(g["text"] for g in p.get("goals", []))
    p["concept_tags"] = [t.id for t in CUR.match_topics(text)] if text.strip() else []


def create(name: str, goal: str = "") -> dict:
    """Idempotent: calling this on an existing project returns its current
    state rather than resetting it, matching record()'s own setdefault
    idiom below."""
    db = _load()
    is_new = name not in db["projects"]
    p = db["projects"].setdefault(name, {
        "created": _now(), "goals": [], "questions": [],
        "decisions": [], "notes": [], "links": [], "concept_tags": [],
        "entries": 0})
    if is_new:
        p["updated"] = p["created"]
        _save(db)
    if goal:
        return record(name, goal=goal)
    return p


def record(name: str, *, goal: str = "", question: str = "",
           decision: str = "", note: str = "", link: str = "") -> dict:
    """Append to a project. `link` is free text naming a research thread or
    curriculum topic id that turned out to matter to this project — kept as
    a single free-form type rather than separate thread-link/topic-link
    types, since nothing yet needs to distinguish them structurally."""
    db = _load()
    p = db["projects"].setdefault(name, {
        "created": _now(), "goals": [], "questions": [],
        "decisions": [], "notes": [], "links": [], "concept_tags": [],
        "entries": 0})
    stamp = _now()
    if goal:
        p["goals"].append({"at": stamp, "text": goal})
        _retag(p)
    if question:
        p["questions"].append({"at": stamp, "text": question, "status": "open"})
    if decision:
        p["decisions"].append({"at": stamp, "text": decision})
    if note:
        p["notes"].append({"at": stamp, "text": note})
    if link:
        p["links"].append({"at": stamp, "text": link})
    p["entries"] += 1
    p["updated"] = stamp
    _save(db)
    return p


def get(name: str) -> dict:
    return _load()["projects"].get(name, {})


def list_projects() -> list[dict]:
    db = _load()
    return [{"project": k,
             "updated": v.get("updated", v.get("created", "")),
             "goals": len(v.get("goals", [])),
             "questions": sum(1 for q in v.get("questions", [])
                              if q.get("status") == "open"),
             "decisions": len(v.get("decisions", [])),
             "notes": len(v.get("notes", [])),
             "links": len(v.get("links", [])),
             "concept_tags": v.get("concept_tags", [])}
            for k, v in sorted(db["projects"].items(),
                               key=lambda kv: kv[1].get("updated", ""), reverse=True)]


def brief(name: str, max_items: int = 6) -> str:
    """Compact prior context for a project, to prime a future question."""
    p = get(name)
    if not p:
        return ""
    bits = []
    if p.get("goals"):
        bits.append("Goal: " + p["goals"][-1]["text"])
    openq = [q for q in p.get("questions", []) if q.get("status") == "open"]
    if openq:
        bits.append("Open questions:\n" + "\n".join(f"  - {q['text']}" for q in openq[-max_items:]))
    if p.get("decisions"):
        bits.append("Decisions made:\n" + "\n".join(
            f"  - {d['text']}" for d in p["decisions"][-max_items:]))
    if p.get("notes"):
        bits.append("Notes:\n" + "\n".join(f"  - {n['text']}" for n in p["notes"][-max_items:]))
    if p.get("links"):
        bits.append("Linked: " + ", ".join(l["text"] for l in p["links"][-max_items:]))
    return "\n\n".join(bits)


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for r in list_projects():
            print(f"  {r['project']:<28s} goals={r['goals']:<3d} open_q={r['questions']:<3d} "
                  f"decisions={r['decisions']:<3d} notes={r['notes']:<3d} tags={r['concept_tags']}")
    elif cmd == "brief":
        print(brief(sys.argv[2]))
