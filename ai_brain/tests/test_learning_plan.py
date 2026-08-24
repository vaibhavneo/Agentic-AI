"""Offline regression test for curriculum.learning_plan() — Phase 4's
"what should I learn next toward X" addition, built on the existing
learning_path() and optionally enriched with the Knowledge Graph's
explained_by edges (Phase 3).

    python3 tests/test_learning_plan.py

No network, no API key, no database: pure function against the real
47-topic TOPICS dict, same convention as test_curriculum_intelligence.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import curriculum as CUR

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


print("[learning_plan: unknown goal topic returns a clean error, not a crash]")
bad = CUR.learning_plan("this-topic-does-not-exist", set())
check("empty known/missing/sequence", bad["known"] == [] and bad["missing"] == [] and bad["sequence"] == [])
check("error field names the bad id", "this-topic-does-not-exist" in bad.get("error", ""))

print("\n[learning_plan: nothing known yet — everything in the sequence is missing]")
plan = CUR.learning_plan("transformer-architecture", set())
check("goal topic is the last step of the sequence", plan["sequence"][-1] == "transformer-architecture",
      str(plan["sequence"]))
check("known is empty", plan["known"] == [])
check("missing equals the entire sequence", plan["missing"] == plan["sequence"])
check("attention-mechanism is a real prerequisite step before the goal",
      "attention-mechanism" in plan["sequence"] and
      plan["sequence"].index("attention-mechanism") < plan["sequence"].index("transformer-architecture"))

print("\n[learning_plan: everything already known — nothing missing]")
plan2 = CUR.learning_plan("transformer-architecture", set(plan["sequence"]))
check("known equals the entire sequence", plan2["known"] == plan2["sequence"])
check("missing is empty", plan2["missing"] == [])

print("\n[learning_plan: partial knowledge splits known/missing correctly, order preserved]")
half_known = set(plan["sequence"][:len(plan["sequence"]) // 2])
plan3 = CUR.learning_plan("transformer-architecture", half_known)
check("known is exactly the intersection with known_ids",
      set(plan3["known"]) == half_known & set(plan3["sequence"]))
check("missing is exactly the complement",
      set(plan3["missing"]) == set(plan3["sequence"]) - half_known)
check("known+missing covers the full sequence with no overlap and no loss",
      sorted(plan3["known"] + plan3["missing"]) == sorted(plan3["sequence"]))
check("relative order within the sequence is preserved in both known and missing",
      [t for t in plan3["sequence"] if t in plan3["known"]] == plan3["known"] and
      [t for t in plan3["sequence"] if t in plan3["missing"]] == plan3["missing"])

print("\n[learning_plan: related_context is present and doesn't duplicate the sequence itself]")
check("related_context is a list", isinstance(plan["related_context"], list))
check("related_context never repeats a topic already in the main sequence",
      not (set(plan["related_context"]) & set(plan["sequence"])), str(plan["related_context"]))

print("\n[learning_plan: a topic with no prerequisites yields a single-step sequence]")
no_prereq = next(t for t in CUR.TOPICS.values() if not t.prerequisites)
plan4 = CUR.learning_plan(no_prereq.id, set())
check(f"'{no_prereq.id}' alone is the whole sequence", plan4["sequence"] == [no_prereq.id])

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
