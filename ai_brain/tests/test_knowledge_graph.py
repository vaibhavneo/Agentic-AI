"""Offline regression test for the Knowledge Graph: the generator's own
validator (tools/generate_knowledge_graph.py's validate_batch — rejects a
hallucinated node id and an invalid relation type without ever calling a
real LLM) and knowledge_graph.py's query module against a small fixture
graph written to a scratch path.

    python3 tests/test_knowledge_graph.py

No network, no API key: validate_batch() is a pure function over already-
parsed dicts, and knowledge_graph.py's index is pure Python built from a
JSON file redirected to a scratch path for this run.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import curriculum as CUR
import generate_knowledge_graph as GEN

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


# ── validate_batch(): the generator's own validator, no LLM involved ───────

real_ids = list(CUR.TOPICS.keys())
a, b, c = real_ids[0], real_ids[1], real_ids[2]

print("[validate_batch: a well-formed batch passes through untouched]")
good = {a: {"related_to": [b], "used_by": [c]}}
edges, dropped = GEN.validate_batch(good, set(real_ids))
check("clean edges preserved", edges == good, str(edges))
check("nothing dropped", dropped == {"bad_source": 0, "bad_target": 0, "bad_type": 0, "self_loop": 0})

print("\n[validate_batch: a hallucinated node id (source) is rejected]")
edges2, dropped2 = GEN.validate_batch(
    {"this-topic-does-not-exist": {"related_to": [a]}}, set(real_ids))
check("hallucinated source dropped entirely", edges2 == {})
check("counted as bad_source", dropped2["bad_source"] == 1)

print("\n[validate_batch: a hallucinated node id (target) is rejected, real targets kept]")
edges3, dropped3 = GEN.validate_batch(
    {a: {"related_to": [b, "also-not-a-real-topic-id"]}}, set(real_ids))
check("real target kept", edges3[a]["related_to"] == [b])
check("hallucinated target counted, not silently kept", dropped3["bad_target"] == 1)

print("\n[validate_batch: an invalid relation-type string is rejected]")
edges4, dropped4 = GEN.validate_batch(
    {a: {"is_similar_to": [b], "related_to": [b]}}, set(real_ids))
check("invalid type key absent from output", "is_similar_to" not in edges4.get(a, {}))
check("valid type key still present", edges4[a]["related_to"] == [b])
check("counted as bad_type", dropped4["bad_type"] == 1)

print("\n[validate_batch: a self-loop is rejected]")
edges5, dropped5 = GEN.validate_batch({a: {"related_to": [a]}}, set(real_ids))
check("self-loop produces no edge for that type", "related_to" not in edges5.get(a, {}))
check("counted as self_loop", dropped5["self_loop"] == 1)

print("\n[validate_batch: malformed shapes (non-dict, non-list) never crash the run]")
edges6, _ = GEN.validate_batch(
    {a: "not a dict", b: {"related_to": "not a list"}, "not a dict at all": None}, set(real_ids))
check("no exception raised, malformed entries just produce no edges", edges6 == {})
edges7, _ = GEN.validate_batch("this whole thing is not even a dict", set(real_ids))
check("a non-dict top-level payload returns empty, not a crash", edges7 == {})


# ── knowledge_graph.py: query module against a small fixture graph ─────────

_tmp = tempfile.TemporaryDirectory()
kg_path = Path(_tmp.name) / "kg.json"

# Use three real topic ids so the module's own valid-id filtering (which
# checks against curriculum.TOPICS) doesn't strip our fixture edges.
t1, t2, t3 = real_ids[0], real_ids[1], real_ids[2]
fixture = {
    "edges": {
        t1: {"used_by": [t2], "related_to": [t3]},
        t3: {"contrasts_with": [t2]},
    }
}
kg_path.write_text(json.dumps(fixture))

import knowledge_graph as KG
KG.KG_PATH = kg_path
KG._RAW = KG._load_raw()
KG._INDEX = KG._build_index(KG._RAW.get("edges", {}))

print(f"\n[bidirectional index: forward edge {t1} --used_by--> {t2} is queryable]")
check("forward direction", t2 in KG.relations(t1, "used_by"))

print(f"[bidirectional index: the REVERSE edge from {t2}'s side works without a separate stored edge]")
check("reverse direction ('uses') was never explicitly stored but is queryable",
      t1 in KG.relations(t2, "uses"), str(KG.relations(t2)))

print("\n[find_path: respects the rel_types filter — a contrasts_with-only edge is not a 'path']")
p_default = KG.find_path(t1, t2)   # default rel_types=("prerequisites",) — no prereq edge exists here
check("no path found via prerequisites when none was stored", p_default is None)

print("[find_path: explicitly asking for 'used_by' finds the direct edge]")
p_used_by = KG.find_path(t1, t2, rel_types=("used_by",))
check("direct used_by path found", p_used_by == [t1, t2], str(p_used_by))

print("[find_path: a same-node query returns a trivial single-node path]")
check("a == b returns [a]", KG.find_path(t1, t1) == [t1])

print("\n[explain_edge: reports the stored relation type in either direction]")
check("a->b direction reports the real type", KG.explain_edge(t1, t2) == f"{t1} --used_by--> {t2}")
check("b->a direction reports the reverse label", KG.explain_edge(t2, t1) == f"{t2} --uses--> {t1}")
check("no edge between two unconnected fixture nodes' non-fixture pairing returns None",
      KG.explain_edge(t2, "nonexistent-topic-id") is None)

print("\n[overlap: shared neighbors and direct-edge reporting]")
ov = KG.overlap(t1, t3)
check("overlap reports the direct edge between t1 and t3", ov["direct_edge"] is not None)

print("\n[prerequisites are folded in automatically from curriculum.py, not just the JSON file]")
# Find a real topic with at least one real prerequisite to test against.
with_prereq = next((t for t in CUR.TOPICS.values() if t.prerequisites), None)
if with_prereq:
    prereq_id = with_prereq.prerequisites[0]
    check(f"'{with_prereq.id}' shows '{prereq_id}' under the prerequisites relation",
          prereq_id in KG.relations(with_prereq.id, "prerequisites"))
    check(f"the reverse 'enables' edge is queryable from '{prereq_id}'",
          with_prereq.id in KG.relations(prereq_id, "enables"))
else:
    check("(skipped — no topic in curriculum.py currently has a prerequisite)", True)

_tmp.cleanup()

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
