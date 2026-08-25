"""Offline regression test for orchestrator.py — the unified front door in
front of pipeline.run() and research_loop.investigate().

    python3 tests/test_orchestrator_routing.py

No network, no API key: pipeline.run()/research_loop.investigate() are
monkey-patched with fake generators for the handle()-level tests, so this
exercises ONLY the routing decision and payload-tagging logic, never a
real LLM call. The pure routing-decision helpers (_wants_research_engine,
_resolve_thread) need no stubbing at all — they're plain functions.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ideas as IDEAS
import projects as PROJ
import research as RESEARCH
import orchestrator as O

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


# ── _wants_research_engine: pure, no stubbing needed ────────────────────────

print("[_wants_research_engine: high-precision trigger phrases fire in auto mode]")
_TRIGGER_CASES = [
    ("search arxiv for retrieval augmented generation", "auto", True),
    ("find recent papers on sparse attention", "auto", True),
    ("find papers about diffusion models", "auto", True),
    ("literature review of parameter efficient fine-tuning", "auto", True),
    ("literature search for agent reliability", "auto", True),
    ("look up recent papers on RAG", "auto", True),
    ("what does research say about RAG vs fine-tuning", "auto", True),
]
for text, mode, expected in _TRIGGER_CASES:
    check(f"{text!r} (mode={mode}) -> research={expected}",
          O._wants_research_engine(text, mode) == expected)

print("\n[_wants_research_engine: the question_type='research' naming collision — the regression case]")
# pipeline.py's own question_type enum already has a value literally called
# "research" (mode="research": a directive-only pipeline mode using the
# SAME evidence every other mode does, not a literature search — never
# touches arXiv, already reachable from the Ask tab's own dropdown). A
# broad "research"/"investigate" keyword net would collide with it; this
# asserts the trigger set stays narrow enough that it doesn't.
_COLLISION_CASES = [
    "give me a research-style answer on transformers",
    "answer this like a research mentor would",
    "what's the current state of research on attention",
    "investigate this question about gradients",
    "what is attention",
    "teach me about backpropagation",
    "challenge my idea about RAG",
]
for text in _COLLISION_CASES:
    check(f"{text!r} does NOT trigger the research engine (stays on pipeline)",
          O._wants_research_engine(text, "auto") is False)

print("\n[_wants_research_engine: an explicit non-auto mode never auto-routes, even with a trigger phrase]")
for mode in ("explain", "research", "thinking_partner", "quiz"):
    check(f"mode={mode!r} suppresses auto-routing even for 'search arxiv for X'",
          O._wants_research_engine("search arxiv for X", mode) is False)


# ── _resolve_thread: pure, no stubbing needed ───────────────────────────────

_tmp_research = tempfile.TemporaryDirectory()
RESEARCH.NOTEBOOK_PATH = Path(_tmp_research.name) / "notebook.json"
RESEARCH.record("lora-efficiency", finding="a real finding")

print("\n[_resolve_thread: fuzzy-matches an existing thread despite hyphens/casing]")
check("hyphenated thread name matches natural phrasing",
      O._resolve_thread("search arxiv about lora efficiency and rank", "") == "lora-efficiency")
check("case-insensitive",
      O._resolve_thread("SEARCH ARXIV ABOUT LORA-EFFICIENCY", "") == "lora-efficiency")
check("no match falls back to the fixed default thread, never an invented slug",
      O._resolve_thread("search arxiv about something totally different", "") == O.DEFAULT_RESEARCH_THREAD)
check("an explicit thread always overrides fuzzy matching",
      O._resolve_thread("search arxiv about lora", "a-different-thread") == "a-different-thread")


# ── handle(): full routing + payload tagging, both engines stubbed ─────────

_tmp_proj = tempfile.TemporaryDirectory()
_tmp_ideas = tempfile.TemporaryDirectory()
PROJ.PROJECTS_PATH = Path(_tmp_proj.name) / "projects.json"
IDEAS.IDEAS_PATH = Path(_tmp_ideas.name) / "ideas.json"


def _fake_pipeline_run(question, mode="explain", depth="intermediate", history=(),
                       project_context="", kg_context="", research_context=""):
    yield "understand", {"msg": "classifying"}
    yield "done", {"prose": f"a pipeline answer to: {question}", "mode": mode,
                   "understanding": {"idea_worthy": False}, "topics": []}


def _fake_investigate(thread, question, depth, use_arxiv=True):
    yield "recall", {"msg": "recalling"}
    yield "done", {"thread": thread, "synthesis": f"a research synthesis for: {question}"}


O.pipeline.run = _fake_pipeline_run
O.research_loop.investigate = _fake_investigate

print("\n[handle: a plain question routes to the pipeline engine, tagged correctly]")
events = list(O.handle("what is attention", explicit_mode="auto"))
stages = [s for s, _ in events]
check("done event present", "done" in stages)
done_payload = next(p for s, p in events if s == "done")
check("engine tagged 'pipeline'", done_payload["engine"] == "pipeline")
check("the fake pipeline's own answer came through", "a pipeline answer to" in done_payload["prose"])

print("\n[handle: a research-trigger question routes to the research engine, tagged correctly]")
events2 = list(O.handle("search arxiv for lora efficiency", explicit_mode="auto"))
stages2 = [s for s, _ in events2]
check("an orchestrate event announces the routing decision", "orchestrate" in stages2)
orch = next(p for s, p in events2 if s == "orchestrate")
check("orchestrate event names the research engine", orch["engine"] == "research")
check("orchestrate event names the fuzzy-matched existing thread",
      orch["thread"] == "lora-efficiency", str(orch))
check("done event present", "done" in stages2)
done2 = next(p for s, p in events2 if s == "done")
check("engine tagged 'research'", done2["engine"] == "research")
check("the fake research engine's own synthesis came through",
      "a research synthesis for" in done2["synthesis"])
check("research-engine events never carry pipeline-only fields like 'prose'",
      "prose" not in done2)

print("\n[handle: empty input is a clean error, not a crash]")
events3 = list(O.handle("   ", explicit_mode="auto"))
check("single error event, no done event", [s for s, _ in events3] == ["error"])

print("\n[handle: an explicit mode='research' (the existing dropdown option) stays on pipeline]")
events4 = list(O.handle("search arxiv for X", explicit_mode="research"))
done4 = next(p for s, p in events4 if s == "done")
check("stays on pipeline engine, never reinterpreted as an engine switch",
      done4["engine"] == "pipeline")

print("\n[handle: 'orchestrate' is distinct from every stage name either real engine uses]")
_REAL_ENGINE_STAGES = ("understand", "route", "gather", "evidence", "reasoning",
                      "professor", "validation", "done", "error",
                      "recall", "search", "survey", "synthesis", "gap", "verify",
                      "record", "drafting")
check("'orchestrate' never collides — a colliding name would silently overwrite "
     "this module's own trace row on the frontend the moment the real engine's "
     "same-named stage fires",
     "orchestrate" not in _REAL_ENGINE_STAGES)

_tmp_research.cleanup()
_tmp_proj.cleanup()
_tmp_ideas.cleanup()

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
