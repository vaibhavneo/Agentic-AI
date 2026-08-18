"""Offline regression test for Milestone 4: prerequisite scaffolding and
cross-source synthesis wiring.

    python3 tests/test_prerequisite_scaffolding.py

No network, no API key: curriculum.prerequisite_gaps() is pure and tested
against the real 47-topic TOPICS dict (not synthetic data — the whole point
is this graph already existed and had zero consumers), and
professor_engine()'s new prereq_topics/agreements plumbing is exercised
against the same _CapturingClient fake test_validation_retry.py established,
which records the prompt sent to the model instead of calling the real API.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import curriculum as CUR
from pipeline import professor_engine

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


print("[prerequisite_gaps: real graph, real topics]")
attention = CUR.TOPICS["attention-mechanism"]
check("attention-mechanism has real prerequisites in TOPICS",
      set(attention.prerequisites) == {"embeddings", "neural-networks-mlp", "numerical-stability"},
      str(attention.prerequisites))

gaps = CUR.prerequisite_gaps([attention])
gap_ids = {t.id for t in gaps}
check("all three direct prerequisites surface as gaps",
      gap_ids == {"embeddings", "neural-networks-mlp", "numerical-stability"}, str(gap_ids))
check("gaps are real Topic objects, not just id strings",
      all(hasattr(t, "title") and hasattr(t, "intuition") for t in gaps))

print("\n[prerequisite_gaps: a prerequisite that's already matched is not a gap]")
embeddings = CUR.TOPICS["embeddings"]
gaps2 = CUR.prerequisite_gaps([attention, embeddings])
gap_ids2 = {t.id for t in gaps2}
check("embeddings excluded — it's already covered, not a gap",
      "embeddings" not in gap_ids2, str(gap_ids2))
# embeddings itself has prerequisites ("vectors-and-matrices",
# "neural-networks-mlp") — passing it in as an already-covered input topic
# correctly surfaces *its* gaps too, on top of attention's remaining two.
check("attention's other two prerequisites plus embeddings' own prerequisite all surface",
      gap_ids2 == {"neural-networks-mlp", "numerical-stability", "vectors-and-matrices"},
      str(gap_ids2))

print("\n[prerequisite_gaps: a topic with no prerequisites yields no gaps]")
no_prereq_topic = next((t for t in CUR.TOPICS.values() if not t.prerequisites), None)
check("found at least one foundations-level topic with no prerequisites",
      no_prereq_topic is not None)
if no_prereq_topic:
    check(f"{no_prereq_topic.id} yields zero gaps",
          CUR.prerequisite_gaps([no_prereq_topic]) == [])

print("\n[prerequisite_gaps: deduplicates across multiple input topics]")
another_dependent = next((t for t in CUR.TOPICS.values()
                          if t.id != "attention-mechanism" and "embeddings" in t.prerequisites), None)
check("found a second real topic that also depends on embeddings", another_dependent is not None,
      another_dependent.id if another_dependent else None)
if another_dependent:
    gaps3 = CUR.prerequisite_gaps([attention, another_dependent])
    check("embeddings appears exactly once despite being a shared prerequisite",
          sum(1 for t in gaps3 if t.id == "embeddings") == 1, str([t.id for t in gaps3]))

print("\n[curriculum_block still renders prerequisite Topics identically to any other topic]")
block = CUR.curriculum_block(gaps[:1])
check("renders a [C:id] tag", f"[C:{gaps[0].id}]" in block, block[:80])


class _CapturingClient:
    def __init__(self):
        self.last_user_prompt = None

        class _Usage:
            prompt_tokens = 10
            completion_tokens = 5
            completion_tokens_details = None

        class _Msg:
            content = "An answer."

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]
            usage = _Usage()

        self._resp = _Resp()

        class _Completions:
            def create(inner_self, model, max_tokens, messages):
                self.last_user_prompt = messages[1]["content"]
                return self._resp

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class _Budget:
    def __init__(self):
        self.by_stage = {}
    def record(self, stage, model, usage, secs):
        self.by_stage[stage] = {"model": model}


print("\n[professor_engine: prereq_topics reach the prompt as a labeled, citable block]")
client = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client, _Budget(),
    topics=(attention,), prereq_topics=(embeddings,))
check("the matched topic's tag is in the prompt", "[C:attention-mechanism]" in client.last_user_prompt)
check("the prerequisite's tag is also in the prompt (citable)",
      "[C:embeddings]" in client.last_user_prompt)
check("prerequisite block is explicitly labeled, not silently merged into main sources",
      "PREREQUISITE BACKGROUND" in client.last_user_prompt)

print("\n[professor_engine: no prereq_topics — no stray empty block]")
client2 = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client2, _Budget(),
    topics=(attention,))
check("no PREREQUISITE BACKGROUND label when there are no gaps",
      "PREREQUISITE BACKGROUND" not in client2.last_user_prompt)

print("\n[professor_engine: agreements reach the prompt — previously silently dropped]")
client3 = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q"}, {"kept": []}, {"hits": []}, None,
    {"skipped": False, "off_topic": [], "conflicts": [], "gaps": [], "confidence": "high",
     "agreements": ["S1 and S3 independently support the scaling factor"]},
    {"text": ""}, "explain", "intermediate", client3, _Budget(), topics=())
check("agreements text reaches the prompt",
      "S1 and S3 independently support the scaling factor" in client3.last_user_prompt)

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
