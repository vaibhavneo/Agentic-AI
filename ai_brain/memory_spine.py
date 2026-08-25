"""The connective layer between AI Brain's separate memory/knowledge
modules — not a replacement for any of them.

mastery.py, conversation.py, research.py, projects.py, ideas.py, and
knowledge_graph.py each keep their own existing internal persistence
exactly as they already work: mastery.record_exposure()/
conversation.append_turn() run inside pipeline.run() as they always have,
research.record() runs inside research_loop.investigate() as it always
has. This module does two things neither of those call sites does on its
own:

  read_context()          — before answering, pull in whatever project,
                             Knowledge Graph, or research-thread context
                             is genuinely relevant to THIS question, as
                             short labeled strings for professor_engine()'s
                             non-citable "extra" block (pipeline.py).
  post_interaction_update() — after answering, write to the genuinely NEW
                             memory types nothing else touches: project
                             notes and idea capture.

Every match here is deterministic set-intersection on topic ids already
computed by curriculum.match_topics() (which the caller runs once, same
as today) — never a new LLM call, never a fabricated connection. Both
functions are engine-agnostic: they take plain data (a list of matched
Topic objects, a question, an answer) rather than a pipeline.py- or
research_loop.py-shaped object, so the same two functions serve either
engine once something calls them — this module doesn't decide who calls
it or when, that's the unified orchestrator's job.
"""
from __future__ import annotations

from typing import Optional

import curriculum as CUR
import ideas as IDEAS
import knowledge_graph as KG
import projects as PROJ
import research as RESEARCH

# Two topics found in both a project/thread and the current question is the
# floor before a connection surfaces automatically — a single shared
# concept among 47 topics is common enough to be noise (matches
# match_topics()'s own real-bug precedent: a weak, incidental overlap must
# not silently attach, see curriculum.py's score-floor comment).
MIN_SHARED_CONCEPTS = 2

# Bounded scans — read_context() runs on every question, so this stays
# cheap and its cost doesn't grow unboundedly as the reader accumulates
# more projects and research threads over time.
MAX_PROJECTS_SCANNED = 20
MAX_THREADS_SCANNED = 10
MAX_KG_TOPICS = 3
MAX_KG_RELATIONS_PER_TOPIC = 5


def _match_project(topic_ids: set) -> Optional[str]:
    if not topic_ids:
        return None
    best_name, best_overlap = None, 0
    for row in PROJ.list_projects()[:MAX_PROJECTS_SCANNED]:
        overlap = len(topic_ids & set(row.get("concept_tags", [])))
        if overlap > best_overlap:
            best_name, best_overlap = row["project"], overlap
    return best_name if best_overlap >= MIN_SHARED_CONCEPTS else None


def _match_research_thread(topic_ids: set) -> Optional[str]:
    if not topic_ids:
        return None
    best_thread, best_overlap = None, 0
    for row in RESEARCH.threads()[:MAX_THREADS_SCANNED]:
        name = row["thread"]
        brief = RESEARCH.brief(name)
        if not brief:
            continue
        thread_topic_ids = {t.id for t in CUR.match_topics(brief)}
        overlap = len(topic_ids & thread_topic_ids)
        if overlap > best_overlap:
            best_thread, best_overlap = name, overlap
    return best_thread if best_overlap >= MIN_SHARED_CONCEPTS else None


def read_context(topics: list, explicit_project: Optional[str] = None) -> dict:
    """Short, labeled context strings for professor_engine()'s extra block.
    `topics` is whatever curriculum.match_topics() already returned for
    this question — nothing here re-derives it. Every value is "" (or None
    for matched_project/matched_research_thread) when nothing genuinely
    applies; callers just check truthiness, same as every other optional
    extra-block field pipeline.py already has."""
    topic_ids = {t.id for t in topics}

    project_name = explicit_project or _match_project(topic_ids)
    project_context = ""
    if project_name:
        brief = PROJ.brief(project_name)
        if brief:
            project_context = f"Project '{project_name}':\n{brief}"
        else:
            project_name = None

    kg_lines = []
    for t in topics[:MAX_KG_TOPICS]:
        rels = KG.relations(t.id)
        if rels:
            kg_lines.append(f"{t.title} relates to: "
                            + ", ".join(rels[:MAX_KG_RELATIONS_PER_TOPIC]))
    kg_context = "\n".join(kg_lines)

    thread_name = _match_research_thread(topic_ids)
    research_context = ""
    if thread_name:
        brief = RESEARCH.brief(thread_name)
        if brief:
            research_context = f"Research thread '{thread_name}':\n{brief}"
        else:
            thread_name = None

    return {
        "project_context": project_context,
        "kg_context": kg_context,
        "research_context": research_context,
        "matched_project": project_name,
        "matched_research_thread": thread_name,
    }


def post_interaction_update(question: str, answer: str, topics: list,
                            idea_worthy: bool = False,
                            matched_project: Optional[str] = None) -> dict:
    """Called once after a meaningful interaction, IN ADDITION TO whatever
    the originating engine already persists on its own — never a
    replacement for mastery.record_exposure()/conversation.append_turn()/
    research.record(), which stay exactly where they are. Only writes the
    memory types nothing else currently writes to: idea capture and
    project notes.

    Call this BEFORE the caller's own terminal SSE yield, matching
    mastery.record_exposure()'s existing pattern and rationale — an SSE
    client can disconnect right after "done", so code after the final
    yield in a generator isn't guaranteed to run.

    Returns what was actually written, for the caller's own trace/logging —
    never everything is written; "" idea capture and no project note is
    the normal, expected case for most interactions (persistence must be
    selective, not automatic)."""
    wrote = {"idea_recorded": False, "project_note_added": False}
    if idea_worthy and answer.strip():
        IDEAS.record(answer[:2000], question=question, project=matched_project or "")
        wrote["idea_recorded"] = True
    if matched_project and topics:
        titles = ", ".join(t.title for t in topics[:3])
        PROJ.record(matched_project,
                   note=f"Touched on: {titles} (from: {question[:200]})")
        wrote["project_note_added"] = True
    return wrote


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "how does attention relate to transformers"
    topics = CUR.match_topics(q)
    ctx = read_context(topics)
    print(f"matched topics: {[t.id for t in topics]}")
    for k, v in ctx.items():
        if v:
            print(f"\n[{k}]\n{v}")
