"""Offline regression test for the "personal AI professor" intelligence
upgrade's curriculum-graph additions: concept_progression(), related_topics(),
recommend_next().

    python3 tests/test_curriculum_intelligence.py

No network, no API key, no database: all three functions are pure and
tested against the real 47-topic TOPICS dict, same convention as
test_prerequisite_scaffolding.py established for prerequisite_gaps().
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


print("[concept_progression: the exact 'attention' example from the spec]")
attention = CUR.TOPICS["attention-mechanism"]
prog = CUR.concept_progression([attention])
prog_ids = [t.id for t in prog]
check("attention-mechanism is the last step (the target concept, taught last)",
      prog_ids[-1] == "attention-mechanism", str(prog_ids))
check("embeddings appears before attention-mechanism (a real prerequisite)",
      "embeddings" in prog_ids and prog_ids.index("embeddings") < prog_ids.index("attention-mechanism"),
      str(prog_ids))
check("every step really is a Topic object with an intuition, not a bare id",
      all(hasattr(t, "intuition") for t in prog))
check("no duplicate steps even though multiple prerequisite paths could repeat one",
      len(prog_ids) == len(set(prog_ids)), str(prog_ids))

print("\n[concept_progression: merges chains across multiple matched topics]")
prog2 = CUR.concept_progression([CUR.TOPICS["attention-mechanism"], CUR.TOPICS["optimizers"]])
prog2_ids = [t.id for t in prog2]
check("both target topics appear in the merged progression",
      "attention-mechanism" in prog2_ids and "optimizers" in prog2_ids, str(prog2_ids))

print("\n[concept_progression: caps a genuinely deep chain, keeping the END (closest to what was asked)]")
deep = CUR.concept_progression([CUR.TOPICS["alignment-and-rlhf"]], cap=5)
check("capped to the requested length", len(deep) == 5, str([t.id for t in deep]))
check("the target topic itself survives the cap (it's the last step)",
      deep[-1].id == "alignment-and-rlhf", str([t.id for t in deep]))

print("\n[concept_progression: a topic with no prerequisites is just itself]")
no_prereq = next(t for t in CUR.TOPICS.values() if not t.prerequisites)
solo = CUR.concept_progression([no_prereq])
check(f"{no_prereq.id} alone yields a single-step progression",
      [t.id for t in solo] == [no_prereq.id], str([t.id for t in solo]))

print("\n[related_topics: attention relates to something, and never to itself]")
rel = CUR.related_topics(attention)
check("returns at least one related topic for a well-connected topic like attention",
      len(rel) > 0, str([t.id for t in rel]))
check("never includes the topic itself", attention.id not in [t.id for t in rel])

print("\n[recommend_next: cold start (no mastery data) still returns real topics]")
cold = CUR.recommend_next(known_ids=set(), exposed_ids=set(), recent_ids=[])
check("cold start returns something", len(cold) > 0, str([t.id for t in cold]))
check("cold-start recommendations are all zero-prerequisite topics (nothing else could be ready)",
      all(not t.prerequisites for t in cold), str([(t.id, t.prerequisites) for t in cold]))

print("\n[recommend_next: only recommends topics whose prerequisites are actually known]")
half_known = {"vectors-and-matrices", "probability-foundations", "calculus-and-gradients"}
recs = CUR.recommend_next(known_ids=half_known, exposed_ids=half_known, recent_ids=[])
for t in recs:
    check(f"{t.id}'s prerequisites are a subset of known_ids (a real gap-based match, not generic)",
          set(t.prerequisites) <= half_known, str(t.prerequisites))

print("\n[recommend_next: never recommends something already exposed]")
exposed = {"vectors-and-matrices", "probability-foundations", "supervised-learning"}
recs2 = CUR.recommend_next(known_ids=exposed, exposed_ids=exposed, recent_ids=[])
check("none of the recommendations were already exposed",
      not any(t.id in exposed for t in recs2), str([t.id for t in recs2]))

print("\n[recommend_next: prefers a topic connected to what was recently studied]")
# Found dynamically from the real TOPICS dict rather than guessed: two
# zero-prerequisite topics (so both are trivially "ready" regardless of what
# else is known) where one shares a key_concept with the chosen recent
# topic and the other doesn't — the minimal real scenario that actually
# exercises the recency tiebreak rather than assuming curriculum content
# that might change later.
zero_prereq = [t for t in CUR.TOPICS.values() if not t.prerequisites]
recent_topic = zero_prereq[0]
recent_concepts = {c.lower() for c in recent_topic.key_concepts}
overlapping = next((t for t in zero_prereq[1:]
                    if recent_concepts & {c.lower() for c in t.key_concepts}), None)
non_overlapping = next((t for t in zero_prereq[1:]
                        if t.id != (overlapping.id if overlapping else None)
                        and not (recent_concepts & {c.lower() for c in t.key_concepts})), None)
if overlapping and non_overlapping:
    recs3 = CUR.recommend_next(known_ids=set(), exposed_ids={recent_topic.id},
                               recent_ids=[recent_topic.id], n=len(zero_prereq))
    rec_ids3 = [t.id for t in recs3]
    check(f"{overlapping.id} (shares a concept with recent topic {recent_topic.id}) "
          f"ranks ahead of {non_overlapping.id} (no shared concept)",
          rec_ids3.index(overlapping.id) < rec_ids3.index(non_overlapping.id), str(rec_ids3))
else:
    # Not a failure of the function — just means no two zero-prerequisite
    # topics in the current curriculum happen to share a concept, so the
    # tiebreak has nothing to demonstrate on this data. Still worth knowing.
    print("  skip  no zero-prerequisite pair with concept overlap exists in the current curriculum")

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
