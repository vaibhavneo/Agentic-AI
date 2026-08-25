"""The unified front door: one dispatcher in front of the two existing
answer engines (pipeline.run() — Teach/Think/Quiz/Socratic/Compare/Paper-
Review, all mode variants of one already-shared pipeline — and
research_loop.investigate() — real arXiv + notebook continuity), plus
memory_spine's connective context. Neither existing engine is modified to
call the other; this module is a caller of both, never a change to either
— the same principle memory_spine.py already applies to
mastery.py/conversation.py/research.py.

Routing is entirely deterministic. No new LLM call, and specifically no
second call to anything understand()-shaped — pipeline.run() already
makes its own understand() call internally when it's chosen, so a
pre-classification step here would double-charge every pipeline-routed
question for nothing.

  1. An explicit thread name (the caller already knows it wants a specific
     research thread) always wins.
  2. A narrow, high-precision set of literature-search trigger phrases
     ("search arxiv", "find papers on", ...) routes to research_loop.
     Deliberately NOT the bare word "research" or "investigate" — those
     already mean something else inside pipeline.run(): question_type=
     "research" (_UNDERSTAND_SYS in pipeline.py) is a directive-only
     "answer like a research mentor" style using the SAME book/web
     evidence every other mode uses, not a literature search — it never
     touches arXiv or the notebook, and it's already reachable from the
     Ask tab's own mode dropdown today. An explicit mode="research" passed
     in here (i.e. the reader picked "Research" from that dropdown) is
     honored as exactly that existing meaning and is NEVER reinterpreted
     as "switch engines" — only mode="auto" is eligible for the trigger-
     phrase check at all, so an explicit dropdown choice can't collide
     with the auto-detector.
  3. Everything else goes to pipeline.run() unchanged, including its own
     understand()-based mode classification when mode="auto" — exactly
     what happens today calling it directly.

For the research_loop branch, the thread is resolved deterministically
too: a substring match against research.threads()'s existing names, else
one fixed default ("general") — never an invented per-question slug.
research_loop.py's entire value is a thread accumulating findings across
runs (see its own module docstring); auto-generated one-shot thread names
would defeat that on every single auto-routed question.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional

import curriculum as CUR
import memory_spine as MS
import pipeline
import research
import research_loop

_RESEARCH_TRIGGERS = (
    r"search arxiv",
    r"find (?:recent )?papers?\s+(?:on|about)",
    r"literature (?:search|review)\s+(?:on|for|of)",
    r"look up (?:recent )?(?:papers|literature)\s+(?:on|about)",
    r"what does (?:recent |the )?research say about",
)
_RESEARCH_TRIGGER_RE = re.compile("|".join(_RESEARCH_TRIGGERS), re.IGNORECASE)

DEFAULT_RESEARCH_THREAD = "general"


def _wants_research_engine(user_input: str, explicit_mode: str) -> bool:
    if explicit_mode and explicit_mode != "auto":
        return False
    return bool(_RESEARCH_TRIGGER_RE.search(user_input))


def _norm(s: str) -> str:
    """Thread names are hyphenated slugs ('lora-efficiency'); natural
    questions aren't ('lora efficiency and rank'). Normalizing hyphens/
    underscores to spaces before comparing is what makes this a genuine
    fuzzy match rather than a literal-substring check that would almost
    never fire in practice."""
    return re.sub(r"[-_]+", " ", s.lower())


def _resolve_thread(user_input: str, explicit_thread: str = "") -> str:
    if explicit_thread:
        return explicit_thread
    low = _norm(user_input)
    for row in research.threads():
        name = row["thread"]
        if _norm(name) in low:
            return name
    return DEFAULT_RESEARCH_THREAD


def handle(user_input: str, explicit_mode: str = "auto", depth: str = "intermediate",
          history=(), explicit_project: Optional[str] = None,
          explicit_thread: str = "") -> Iterator[tuple]:
    """SSE-shaped exactly like pipeline.run()/research_loop.investigate()
    already are — (stage, payload) pairs. Every payload gets a new
    "engine" key ("pipeline" or "research") so a single frontend handler
    can branch on it. Stage names use "orchestrate" for this module's own
    routing/context announcements — deliberately NOT "route", which
    pipeline.run() already uses internally for its own stage 3; reusing
    that name would silently overwrite this module's trace row on the
    frontend the moment pipeline.run()'s own route() stage fires."""
    user_input = (user_input or "").strip()
    if not user_input:
        yield "error", {"message": "empty question"}
        return

    if _wants_research_engine(user_input, explicit_mode):
        thread = _resolve_thread(user_input, explicit_thread)
        yield "orchestrate", {"msg": f"Routed to the research engine — thread '{thread}'",
                              "engine": "research", "thread": thread}
        for stage, payload in research_loop.investigate(thread, user_input, depth, use_arxiv=True):
            payload = dict(payload)
            payload["engine"] = "research"
            yield stage, payload
        return

    # pipeline engine. topics computed once here for memory_spine's
    # context lookup — a second, cheap call to the same pure function
    # pipeline.run() also calls internally for its own citation purposes
    # (CUR.match_topics(), no LLM, sub-millisecond); not worth threading a
    # pre-computed list through run()'s signature just to avoid that.
    topics = CUR.match_topics(user_input)
    ctx = MS.read_context(topics, explicit_project=explicit_project)
    if ctx["matched_project"]:
        yield "orchestrate", {"msg": f"Project '{ctx['matched_project']}' context attached",
                              "engine": "pipeline", "matched_project": ctx["matched_project"]}
    if ctx["matched_research_thread"]:
        yield "orchestrate", {
            "msg": f"Research thread '{ctx['matched_research_thread']}' context attached",
            "engine": "pipeline", "matched_research_thread": ctx["matched_research_thread"]}

    for stage, payload in pipeline.run(
            user_input, mode=explicit_mode, depth=depth, history=history,
            project_context=ctx["project_context"], kg_context=ctx["kg_context"],
            research_context=ctx["research_context"]):
        payload = dict(payload)
        payload["engine"] = "pipeline"
        yield stage, payload
        if stage == "done":
            understanding = payload.get("understanding") or {}
            done_topics = [CUR.TOPICS[t["id"]] for t in payload.get("topics", [])
                           if t["id"] in CUR.TOPICS] or topics
            MS.post_interaction_update(
                user_input, payload.get("prose", ""), done_topics,
                idea_worthy=bool(understanding.get("idea_worthy")),
                matched_project=ctx["matched_project"])
