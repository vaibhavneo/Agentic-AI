"""Offline regression test for reliability-weighted evidence (the
evidence-driven upgrade's Phase 1a): brain_tutor.py's SHELF_RELIABILITY /
_weighted_score() / retrieve_evidence()'s re-ranking by weighted_score
instead of raw BM25 score.

    python3 tests/test_evidence_weighting.py

No network, no API key, no real corpora — same synthetic-dict pattern as
test_retrieve_dedup.py, extended with a shelf_reliability field on each item
(retrieve_evidence() itself attaches this from SHELF_RELIABILITY before
calling _filter_and_dedup(); these tests exercise _weighted_score() and the
re-ranking directly, at the same level test_retrieve_dedup.py already tests
_filter_and_dedup() at).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain_tutor import (_DEFAULT_SHELF_RELIABILITY, _filter_and_dedup,
                         _weighted_score, SHELF_RELIABILITY, BRAIN_CORPORA)

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


def item(text, shelf, source, score=20.0, shelf_reliability=1.0):
    return {"text": text, "shelf": shelf, "source": source, "raw_score": score,
            "shelf_reliability": shelf_reliability}


REAL_TEXT = (
    "Backpropagation computes the gradient of the loss with respect to each "
    "weight by applying the chain rule backwards through the network, layer "
    "by layer, reusing partial derivatives computed for later layers so the "
    "whole pass costs about the same as one forward evaluation of the network "
    "rather than one evaluation per weight." * 3
)
DISTINCT_TEXT = (
    "Batch normalization rescales the activations of each mini-batch to have "
    "zero mean and unit variance before applying a learned scale and shift, "
    "which keeps gradients well-behaved as the input distribution to each "
    "layer drifts during training." * 3
)
THIRD_TEXT = (
    "Dropout randomly zeroes a fraction of activations during training, which "
    "prevents co-adaptation between units and acts as an implicit ensemble "
    "over the exponentially many thinned sub-networks that remain." * 3
)

print("[SHELF_RELIABILITY covers every real shelf]")
check("every BRAIN_CORPORA id has a reliability entry",
      all(cid in SHELF_RELIABILITY for cid in BRAIN_CORPORA))
check("reliability values are all in (0, 1]",
      all(0 < v <= 1.0 for v in SHELF_RELIABILITY.values()))

print("\n[_weighted_score: pure relevance x reliability, no corroboration]")
solo = item(REAL_TEXT, "deep learning", "a.pdf", score=20.0, shelf_reliability=0.5)
check("single-shelf item: weighted_score == raw_score x reliability (no bonus)",
      _weighted_score(solo) == 10.0, str(_weighted_score(solo)))

print("\n[_weighted_score: unrecognized shelf falls back to the default reliability]")
no_reliability_field = {"text": "x", "shelf": "ai", "source": "y.pdf", "raw_score": 10.0}
check("missing shelf_reliability field defaults to _DEFAULT_SHELF_RELIABILITY",
      _weighted_score(no_reliability_field) == round(10.0 * _DEFAULT_SHELF_RELIABILITY, 3))

print("\n[reliability + corroboration can flip the ranking BM25 alone would give]")
scored = [
    item(REAL_TEXT, "deep learning", "a.pdf", score=25.0, shelf_reliability=0.6),   # single-shelf, lower reliability
    item(DISTINCT_TEXT, "mathematics", "b.pdf", score=20.0, shelf_reliability=1.0),  # will be corroborated
    item(DISTINCT_TEXT, "computer science", "c.pdf", score=19.5, shelf_reliability=1.0),  # near-dup of b.pdf
]
kept, rejected, deduped = _filter_and_dedup(scored)
check("b.pdf absorbed c.pdf as a second corroborating shelf",
      kept[[k["source"] for k in kept].index("b.pdf")].get("shelves") == ["mathematics", "computer science"])
for c in kept:
    c["weighted_score"] = _weighted_score(c)
ranked = sorted(kept, key=lambda c: -c["weighted_score"])
check("higher raw_score (a.pdf, 25.0) does NOT win once reliability+corroboration are weighed",
      ranked[0]["source"] == "b.pdf", str([(c["source"], c["weighted_score"]) for c in ranked]))
check("a.pdf's own raw_score is still the largest of the two — the flip is real, not a tie",
      max(c["raw_score"] for c in kept if c["source"] == "a.pdf") >
      max(c["raw_score"] for c in kept if c["source"] == "b.pdf"))

print("\n[corroboration bonus is capped at 3 shelves]")
three_way = item(THIRD_TEXT, "ai", "d.pdf", score=10.0, shelf_reliability=1.0)
three_way["shelves"] = ["ai", "machine learning", "deep learning"]
five_way = item(THIRD_TEXT, "ai", "e.pdf", score=10.0, shelf_reliability=1.0)
five_way["shelves"] = ["ai", "machine learning", "deep learning", "nlp", "robotics"]
check("3-shelf and 5-shelf corroboration score identically (capped, not unbounded)",
      _weighted_score(three_way) == _weighted_score(five_way),
      f"{_weighted_score(three_way)} vs {_weighted_score(five_way)}")

print("\n[tags are stable across reordering — dedup's merged_into references stay valid]")
scored2 = [
    item(REAL_TEXT, "deep learning", "high-raw.pdf", score=15.0, shelf_reliability=0.5),
    item(DISTINCT_TEXT, "mathematics", "low-raw-high-reliability.pdf", score=10.0, shelf_reliability=1.0),
]
kept2, _, _ = _filter_and_dedup(scored2)
original_tags = {c["source"]: c["tag"] for c in kept2}
for c in kept2:
    c["weighted_score"] = _weighted_score(c)
kept2.sort(key=lambda c: -c["weighted_score"])
check("list order changed (the lower-raw, higher-reliability item now leads)",
      kept2[0]["source"] == "low-raw-high-reliability.pdf")
check("each item's tag is unchanged after reordering",
      all(c["tag"] == original_tags[c["source"]] for c in kept2))

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
