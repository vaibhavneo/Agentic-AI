"""Offline regression test for projects.py — the new Project system's
notebook-style store (create/record/get/list_projects/brief), mirroring
test_research_notebook.py's structure for research.py's notebook.

    python3 tests/test_projects.py

No network, no API key: curriculum.match_topics() is pure Python over the
hardcoded TOPICS dict, and projects.py's store is pure JSON-file I/O
redirected to a scratch path for this run.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import projects as P

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


_tmp = tempfile.TemporaryDirectory()
P.PROJECTS_PATH = Path(_tmp.name) / "projects.json"

print("[create: new project is stored with the expected empty shape]")
P.create("stock-ai-agent", goal="Build a multi-agent stock research pipeline")
p = P.get("stock-ai-agent")
check("project exists after create", bool(p))
check("goal recorded", p["goals"][-1]["text"] == "Build a multi-agent stock research pipeline")
check("entries counter incremented", p["entries"] == 1)
check("questions/decisions/notes/links start empty",
      p["questions"] == [] and p["decisions"] == [] and p["notes"] == [] and p["links"] == [])

print("\n[create: idempotent — calling again on an existing project does not wipe it]")
before = P.get("stock-ai-agent")["entries"]
P.create("stock-ai-agent")
after = P.get("stock-ai-agent")["entries"]
check("entries unchanged by a no-goal create() on an existing project", before == after,
      f"{before} -> {after}")

print("\n[create: concept_tags computed from goal text via curriculum.match_topics]")
check("concept_tags is a list (may be empty if nothing scores above the match floor)",
      isinstance(p.get("concept_tags"), list))

print("\n[record: each entry type appends independently and stamps 'at']")
P.record("stock-ai-agent", question="Does agent reliability research apply here?")
P.record("stock-ai-agent", decision="Use a 5-agent pipeline, trimmed from 7")
P.record("stock-ai-agent", note="Evidence-weighting upgrade shipped this session")
P.record("stock-ai-agent", link="agent-reliability")
p2 = P.get("stock-ai-agent")
check("question recorded with open status", p2["questions"][-1]["status"] == "open")
check("decision recorded", p2["decisions"][-1]["text"] == "Use a 5-agent pipeline, trimmed from 7")
check("note recorded", p2["notes"][-1]["text"] == "Evidence-weighting upgrade shipped this session")
check("link recorded", p2["links"][-1]["text"] == "agent-reliability")
check("every entry carries an 'at' timestamp",
      all("at" in p2[k][-1] for k in ("questions", "decisions", "notes", "links")))

print("\n[record: a second goal re-tags from the FULL accumulated goal text, not just the new sentence]")
P.record("stock-ai-agent", goal="Also explore options-flow signals")
p3 = P.get("stock-ai-agent")
check("both goal entries retained (append-only, not overwritten)", len(p3["goals"]) == 2)

print("\n[record: fields left blank are simply not appended — no stray empty entries]")
before_counts = {k: len(p3[k]) for k in ("questions", "decisions", "notes", "links")}
P.record("stock-ai-agent", note="just a note this time")
p4 = P.get("stock-ai-agent")
check("only notes grew", len(p4["notes"]) == before_counts["notes"] + 1)
check("questions/decisions/links unchanged",
      len(p4["questions"]) == before_counts["questions"] and
      len(p4["decisions"]) == before_counts["decisions"] and
      len(p4["links"]) == before_counts["links"])

print("\n[record: creates the project on first use, same setdefault idiom as research.py]")
P.record("fresh-project", note="first entry ever")
check("project auto-created by record()", bool(P.get("fresh-project")))

print("\n[list_projects: summary shape and sort order]")
P.create("older-project")
lst = P.list_projects()
names = [r["project"] for r in lst]
check("all three projects present", set(names) == {"stock-ai-agent", "fresh-project", "older-project"})
check("sorted by updated, most recent first", names[0] in ("fresh-project", "stock-ai-agent"))
row = next(r for r in lst if r["project"] == "stock-ai-agent")
check("summary counts match the full record",
      row["goals"] == 2 and row["decisions"] == 1 and row["links"] == 1, str(row))

print("\n[brief: labeled blocks, only for non-empty sections]")
b = P.brief("stock-ai-agent")
check("goal block shows the LATEST goal, not the first",
      "Also explore options-flow signals" in b and b.index("Also explore") < len(b))
check("open questions block present", "Open questions" in b and "agent reliability research" in b)
check("decisions block present", "Decisions made" in b and "5-agent pipeline" in b)
check("notes block present", "Notes" in b and "just a note this time" in b)
check("linked block present", "Linked" in b and "agent-reliability" in b)

print("\n[brief: a project with only one entry type has no stray blocks for the others]")
b2 = P.brief("fresh-project")
check("no goal block when no goal was ever recorded", "Goal:" not in b2)
check("no open-questions block", "Open questions" not in b2)
check("notes block present", "Notes" in b2 and "first entry ever" in b2)

print("\n[brief: an unknown project returns an empty string, not an error]")
check("empty string for a project that doesn't exist", P.brief("never-heard-of-this-project") == "")

print("\n[get: an unknown project returns {}, not an error]")
check("empty dict for a project that doesn't exist", P.get("never-heard-of-this-project") == {})

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
_tmp.cleanup()
sys.exit(1 if fails else 0)
