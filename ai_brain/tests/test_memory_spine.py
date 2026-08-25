"""Offline regression test for memory_spine.py — the connective layer
between projects/knowledge_graph/research, and for ideas.py, the new
idea-memory store it writes to.

    python3 tests/test_memory_spine.py

No network, no API key: every match is deterministic set-intersection over
already-computed curriculum.match_topics() output; projects.py/research.py/
ideas.py are pure JSON-file I/O redirected to scratch paths for this run.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import curriculum as CUR
import ideas as IDEAS
import projects as PROJ
import research as RESEARCH
import memory_spine as MS

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


_tmp_proj = tempfile.TemporaryDirectory()
_tmp_research = tempfile.TemporaryDirectory()
_tmp_ideas = tempfile.TemporaryDirectory()
PROJ.PROJECTS_PATH = Path(_tmp_proj.name) / "projects.json"
RESEARCH.NOTEBOOK_PATH = Path(_tmp_research.name) / "notebook.json"
IDEAS.IDEAS_PATH = Path(_tmp_ideas.name) / "ideas.json"

# Two real topics with a real, direct relation in the generated Knowledge
# Graph (confirmed earlier this session): transformer-architecture and
# attention-mechanism.
t_transformer = CUR.TOPICS["transformer-architecture"]
t_attention = CUR.TOPICS["attention-mechanism"]
t_unrelated = CUR.TOPICS["electronics-foundations"]

print("[read_context: no project, no thread, nothing exists yet — every field is empty/None]")
ctx0 = MS.read_context([t_transformer])
check("project_context empty", ctx0["project_context"] == "")
check("research_context empty", ctx0["research_context"] == "")
check("matched_project is None", ctx0["matched_project"] is None)
check("matched_research_thread is None", ctx0["matched_research_thread"] is None)

print("\n[read_context: kg_context surfaces real Knowledge Graph relations for matched topics]")
check("kg_context is non-empty for a topic with real generated edges",
      bool(ctx0["kg_context"]), ctx0["kg_context"][:120])

print("\n[read_context: a project below the concept-overlap floor does NOT auto-attach]")
PROJ.create("weakly-related-project", goal="something about electronics only")
ctx1 = MS.read_context([t_transformer])
check("weak/no overlap does not attach", ctx1["matched_project"] is None)

print("\n[read_context: a project clearing the floor (>=2 shared concepts) DOES auto-attach]")
# Build a project whose concept_tags will genuinely overlap >=2 with a
# transformer-architecture question, using the SAME match_topics() the
# project itself tags with, so this reflects real matching, not a stub.
PROJ.create("transformer-research-project",
           goal="Understanding the transformer block, attention mechanism, and positional encoding deeply")
p = PROJ.get("transformer-research-project")
check("project actually got real concept_tags from match_topics()",
      len(p.get("concept_tags", [])) >= 2, str(p.get("concept_tags")))
ctx2 = MS.read_context([t_transformer, t_attention])
check("strong overlap auto-attaches the project",
      ctx2["matched_project"] == "transformer-research-project", str(ctx2["matched_project"]))
check("project_context carries the project's own brief() text",
      "transformer block" in ctx2["project_context"].lower() or
      "attention" in ctx2["project_context"].lower(), ctx2["project_context"])

print("\n[read_context: explicit_project always overrides auto-match]")
PROJ.create("explicitly-chosen-project", goal="unrelated to anything")
ctx3 = MS.read_context([t_transformer, t_attention], explicit_project="explicitly-chosen-project")
check("explicit project wins even though it wouldn't have auto-matched",
      ctx3["matched_project"] == "explicitly-chosen-project")

print("\n[read_context: a research thread below the floor does NOT auto-attach]")
RESEARCH.record("unrelated-thread", finding="something about electronics circuits only")
ctx4 = MS.read_context([t_transformer, t_attention])
# transformer-research-project still wins on the project axis; check the
# THREAD axis specifically stayed unmatched for unrelated content.
check("electronics-only thread does not match a transformer question",
      ctx4["matched_research_thread"] != "unrelated-thread")

print("\n[read_context: a research thread clearing the floor DOES auto-attach]")
RESEARCH.record("attention-research-thread",
                finding="The transformer block relies on the attention mechanism and "
                        "positional encoding for sequence modeling.")
ctx5 = MS.read_context([t_transformer, t_attention])
check("strong-overlap thread auto-attaches",
      ctx5["matched_research_thread"] == "attention-research-thread",
      str(ctx5["matched_research_thread"]))
check("research_context carries the thread's own brief() text",
      "transformer" in ctx5["research_context"].lower())

print("\n[read_context: no topics at all — nothing crashes, everything empty]")
ctx6 = MS.read_context([])
check("empty topics list handled cleanly",
      ctx6 == {"project_context": "", "kg_context": "", "research_context": "",
              "matched_project": None, "matched_research_thread": None})

print("\n[post_interaction_update: idea_worthy=False writes nothing]")
before_ideas = len(IDEAS.all_ideas())
wrote0 = MS.post_interaction_update("a normal question", "a normal answer", [t_transformer],
                                    idea_worthy=False, matched_project=None)
check("nothing reported as written", wrote0 == {"idea_recorded": False, "project_note_added": False})
check("ideas store unchanged", len(IDEAS.all_ideas()) == before_ideas)

print("\n[post_interaction_update: idea_worthy=True records the idea]")
wrote1 = MS.post_interaction_update("what if we tried retrieval-first agents",
                                    "Here's a fleshed-out idea for retrieval-first agents...",
                                    [t_transformer], idea_worthy=True, matched_project=None)
check("idea_recorded is True", wrote1["idea_recorded"] is True)
latest_idea = IDEAS.recent(1)[0]
check("the idea's question is preserved", latest_idea["question"] == "what if we tried retrieval-first agents")
check("the idea's text is the (truncated) answer", "retrieval-first agents" in latest_idea["text"])
check("no project on this one since none was matched", latest_idea["project"] == "")

print("\n[post_interaction_update: a matched project gets a note appended]")
before_notes = len(PROJ.get("transformer-research-project").get("notes", []))
wrote2 = MS.post_interaction_update("tell me about attention", "attention is...",
                                    [t_attention], idea_worthy=False,
                                    matched_project="transformer-research-project")
check("project_note_added is True", wrote2["project_note_added"] is True)
after_notes = len(PROJ.get("transformer-research-project").get("notes", []))
check("a real note was appended", after_notes == before_notes + 1)
check("the note mentions the matched topic", "Attention" in PROJ.get("transformer-research-project")["notes"][-1]["text"])

print("\n[post_interaction_update: both idea and project can fire together]")
wrote3 = MS.post_interaction_update("idea: combine retrieval with agents for this project",
                                    "a genuinely new idea worth keeping",
                                    [t_transformer], idea_worthy=True,
                                    matched_project="transformer-research-project")
check("both fired", wrote3 == {"idea_recorded": True, "project_note_added": True})
check("the recorded idea carries the project name this time",
      IDEAS.recent(1)[0]["project"] == "transformer-research-project")

print("\n[post_interaction_update: an empty answer never records an idea even if flagged idea_worthy]")
before = len(IDEAS.all_ideas())
MS.post_interaction_update("q", "   ", [t_transformer], idea_worthy=True, matched_project=None)
check("no idea recorded for a blank answer", len(IDEAS.all_ideas()) == before)

_tmp_proj.cleanup()
_tmp_research.cleanup()
_tmp_ideas.cleanup()

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
