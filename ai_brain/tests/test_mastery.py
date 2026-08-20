"""Offline regression test for Milestone 5's mastery store.

    python3 tests/test_mastery.py

No network, no API key: mastery.py is pure stdlib sqlite3 against a real
temp database file (not mocked — sqlite3 is deterministic and fast enough
that a mock would only hide real schema/query bugs). _DB_PATH is redirected
to a scratch file for the whole run so this never touches the real
memory/mastery.db.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import mastery

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


_tmp = tempfile.TemporaryDirectory()
mastery._DB_PATH = Path(_tmp.name) / "mastery.db"

print("[record_exposure: writes real rows, one per topic]")
mastery.record_exposure(["embeddings", "numerical-stability"], "prereq", depth="intro", verdict="pass")
mastery.record_exposure(["attention-mechanism"], "direct", depth="intermediate", verdict="pass")
summary = {r["topic_id"]: r for r in mastery.mastery_summary()}
check("embeddings recorded as prereq", summary["embeddings"]["prereq_count"] == 1,
      str(summary.get("embeddings")))
check("attention-mechanism recorded as direct", summary["attention-mechanism"]["direct_count"] == 1)
check("exposure_count is the sum of direct+prereq for that topic",
      summary["embeddings"]["exposure_count"] == 1)

print("\n[record_exposure: empty list is a no-op, not an error]")
before = len(mastery.mastery_summary())
mastery.record_exposure([], "direct")
after = len(mastery.mastery_summary())
check("no new rows from an empty topic list", before == after, f"{before} -> {after}")

print("\n[record_exposure: repeated calls accumulate, not overwrite]")
for _ in range(3):
    mastery.record_exposure(["gradient-descent"], "direct")
summary = {r["topic_id"]: r for r in mastery.mastery_summary()}
check("three direct exposures accumulate to direct_count=3",
      summary["gradient-descent"]["direct_count"] == 3, str(summary["gradient-descent"]))

print("\n[mark_topic: round-trips through mastery_summary]")
rec = mastery.mark_topic("embeddings", "known")
check("mark_topic returns the new status", rec["status"] == "known", str(rec))
summary = {r["topic_id"]: r for r in mastery.mastery_summary()}
check("mastery_summary reflects the manual status",
      summary["embeddings"]["manual_status"] == "known", str(summary["embeddings"]))

print("\n[mark_topic: overwrite an existing mark]")
rec2 = mastery.mark_topic("embeddings", "review")
check("status updates in place, not a duplicate row", rec2["status"] == "review", str(rec2))
summary = {r["topic_id"]: r for r in mastery.mastery_summary()}
check("only one manual_status row exists for this topic (no duplicate)",
      summary["embeddings"]["manual_status"] == "review")

print("\n[mark_topic: clearing a mark with status=None]")
mastery.mark_topic("embeddings", None)
summary = {r["topic_id"]: r for r in mastery.mastery_summary()}
check("manual_status is back to None after clearing",
      summary["embeddings"]["manual_status"] is None, str(summary.get("embeddings")))
check("exposure history survives clearing the manual mark (it's a separate table)",
      summary["embeddings"]["prereq_count"] == 1)

print("\n[a topic with only a manual mark and zero exposure still appears in the summary]")
mastery.mark_topic("backpropagation", "known")
summary = {r["topic_id"]: r for r in mastery.mastery_summary()}
check("backpropagation appears with zero exposure counts",
      summary["backpropagation"]["exposure_count"] == 0 and
      summary["backpropagation"]["manual_status"] == "known", str(summary.get("backpropagation")))

print("\n[known_topic_ids: manual 'known' and high direct_count both qualify]")
known = mastery.known_topic_ids()
check("manually-marked backpropagation is known", "backpropagation" in known, str(known))
check("gradient-descent with direct_count=3 (the default threshold) is known",
      "gradient-descent" in known, str(known))
check("attention-mechanism with direct_count=1 is NOT known",
      "attention-mechanism" not in known, str(known))
check("embeddings (prereq exposure only, mark cleared) is NOT known",
      "embeddings" not in known, str(known))

print("\n[known_topic_ids: threshold is configurable]")
known_low = mastery.known_topic_ids(min_direct_count=1)
check("with threshold 1, attention-mechanism now qualifies too",
      "attention-mechanism" in known_low, str(known_low))

print("\n[integration: the exact filter pipeline.py's stage 2b applies to prereq_topics]")
import curriculum as CUR

attention = CUR.TOPICS["attention-mechanism"]
gaps = CUR.prerequisite_gaps([attention])
gap_ids_before = {t.id for t in gaps}
check("sanity: attention's real prerequisites still include embeddings",
      "embeddings" in gap_ids_before, str(gap_ids_before))

# Mimic pipeline.py's run() exactly: mark one prerequisite "known", give
# another enough direct exposure to cross the threshold, then apply the
# same filter stage 2b applies.
mastery.mark_topic("embeddings", "known")
for _ in range(mastery.KNOWN_AFTER_DIRECT_COUNT):
    mastery.record_exposure(["numerical-stability"], "direct")
known = mastery.known_topic_ids()
filtered = [t for t in gaps if t.id not in known]
filtered_ids = {t.id for t in filtered}

check("manually-known embeddings no longer reaches professor_engine",
      "embeddings" not in filtered_ids, str(filtered_ids))
check("numerical-stability (direct_count over threshold) no longer reaches professor_engine",
      "numerical-stability" not in filtered_ids, str(filtered_ids))
check("neural-networks-mlp (untouched) still reaches professor_engine as background",
      "neural-networks-mlp" in filtered_ids, str(filtered_ids))
check("filtering only removes known topics, doesn't add or reorder others",
      filtered_ids == gap_ids_before - {"embeddings", "numerical-stability"},
      f"{filtered_ids} vs expected {gap_ids_before - {'embeddings', 'numerical-stability'}}")

print("\n[the intelligence upgrade: recently_studied, weak_topics, exposed_topic_ids, quiz]")
_tmp2 = tempfile.TemporaryDirectory()
mastery._DB_PATH = Path(_tmp2.name) / "mastery2.db"

mastery.record_exposure(["embeddings"], "direct", verdict="pass")
mastery.record_exposure(["attention-mechanism"], "direct", verdict="pass")
check("recently_studied returns direct exposures, most recent first",
      mastery.recently_studied() == ["attention-mechanism", "embeddings"],
      str(mastery.recently_studied()))
mastery.record_exposure(["numerical-stability"], "prereq", verdict="pass")
check("recently_studied excludes prereq-only exposures (never the actual subject of an answer)",
      "numerical-stability" not in mastery.recently_studied(), str(mastery.recently_studied()))

check("exposed_topic_ids includes both direct and prereq exposures",
      mastery.exposed_topic_ids() == {"embeddings", "attention-mechanism", "numerical-stability"},
      str(mastery.exposed_topic_ids()))

mastery.record_exposure(["backpropagation"], "direct", verdict="pass")
mastery.record_exposure(["backpropagation"], "direct", verdict="fail")
mastery.record_exposure(["backpropagation"], "direct", verdict="fail")
check("weak_topics surfaces a topic asked about repeatedly with more non-pass than pass verdicts",
      "backpropagation" in mastery.weak_topics(), str(mastery.weak_topics()))
check("weak_topics does not flag a topic seen only once (not enough of a pattern)",
      "attention-mechanism" not in mastery.weak_topics(), str(mastery.weak_topics()))

mastery.mark_topic("optimizers", "review")
check("a manually-marked 'review' topic leads weak_topics even with no exposure history",
      mastery.weak_topics()[0] == "optimizers", str(mastery.weak_topics()))

check("quiz_stats on an untouched topic reports zero attempts, no accuracy",
      mastery.quiz_stats("embeddings") == {"topic_id": "embeddings", "attempts": 0,
                                           "correct": 0, "accuracy": None},
      str(mastery.quiz_stats("embeddings")))
mastery.record_quiz_result("embeddings", True)
mastery.record_quiz_result("embeddings", False)
qs = mastery.quiz_stats("embeddings")
check("record_quiz_result + quiz_stats: 2 attempts, 1 correct, accuracy 0.5",
      qs == {"topic_id": "embeddings", "attempts": 2, "correct": 1, "accuracy": 0.5}, str(qs))
check("quiz exposures do not count toward direct_count (a quiz attempt isn't being taught)",
      mastery.mastery_summary()[0].get("direct_count", 0) is not None and
      all(r["topic_id"] != "embeddings" or r["direct_count"] == 1
          for r in mastery.mastery_summary()),
      "embeddings had exactly one real direct exposure before the quiz calls")

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
_tmp.cleanup()
_tmp2.cleanup()
sys.exit(1 if fails else 0)
