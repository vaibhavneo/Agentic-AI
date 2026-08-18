"""Offline regression test for Milestone 2 Step 1: dedup near-duplicate
passages across shelves.

    python3 tests/test_retrieve_dedup.py

No network, no API key, no real corpora — _filter_and_dedup() is pure
Python over synthetic dicts shaped like retrieve_evidence()'s `scored` list.
Mirrors second_brain/tests/test_gateway.py::test_dedup_keeps_both_provenances
(the existing precedent for testing this exact algorithm, on the unused
gateway/TF-IDF path) but proves the property that test doesn't need to:
that a duplicate does not consume a KEEP_K slot a distinct passage could
have taken, since brain_tutor.py's KEEP_K cutoff and the dedup check now
live in the same loop.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain_tutor import KEEP_K, MIN_RAW_SCORE, _filter_and_dedup, _near_dup, _shingles

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


def item(text, shelf, source, score=20.0):
    return {"text": text, "shelf": shelf, "source": source, "raw_score": score}


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

print("[near-duplicate across two shelves — one survivor, both provenances kept]")
scored = [
    item(REAL_TEXT, "deep learning", "book-a.pdf", score=25.0),
    item(REAL_TEXT, "machine learning", "book-b.pdf", score=20.0),
]
kept, rejected, deduped = _filter_and_dedup(scored)
check("exactly one survivor in kept", len(kept) == 1, str(len(kept)))
check("survivor is the higher-scored copy", kept[0]["source"] == "book-a.pdf" if kept else False)
check("survivor carries both shelves", kept[0].get("shelves") == ["deep learning", "machine learning"] if kept else False, str(kept[0].get("shelves") if kept else None))
check("survivor carries both sources", kept[0].get("sources") == ["book-a.pdf", "book-b.pdf"] if kept else False)
check("loser recorded in deduped, not rejected", len(deduped) == 1 and len(rejected) == 0, f"deduped={len(deduped)} rejected={len(rejected)}")
check("deduped item points at the survivor's tag", deduped[0].get("merged_into") == "S1" if deduped else False)

print("\n[KEEP_K duplicates of the top hit + one distinct item — slot reclaimed]")
scored = [item(REAL_TEXT, "deep learning", f"dup-{i}.pdf", score=30.0 - i)
          for i in range(KEEP_K)]
scored.append(item(DISTINCT_TEXT, "computer vision", "distinct.pdf", score=5.0))
kept, rejected, deduped = _filter_and_dedup(scored)
check("only one of the KEEP_K duplicates survives", len(kept) == 2, f"kept={len(kept)}")
check("the distinct item made it into kept despite ranking below all duplicates",
      any(k["source"] == "distinct.pdf" for k in kept))
check(f"all {KEEP_K - 1} extra duplicates landed in deduped, not silently dropped",
      len(deduped) == KEEP_K - 1, str(len(deduped)))

print("\n[no near-dup pair ever coexists in kept]")
scored = [
    item(REAL_TEXT, "ai", "a.pdf", score=25.0),
    item(DISTINCT_TEXT, "ai", "b.pdf", score=24.0),
    item(REAL_TEXT + " extra trailing sentence that still overlaps heavily.", "nlp", "c.pdf", score=23.0),
]
kept, rejected, deduped = _filter_and_dedup(scored)
check("kept has no internal near-dup pair",
      all(not _near_dup(kept[i]["text"], kept[j]["text"])
          for i in range(len(kept)) for j in range(i + 1, len(kept))),
      str([k["source"] for k in kept]))
check("the two genuinely distinct passages both survive", len(kept) == 2, str(len(kept)))

print("\n[quality filters still apply before dedup ever runs]")
scored = [item("too short", "ai", "short.pdf", score=25.0)]
kept, rejected, deduped = _filter_and_dedup(scored)
check("a too-short item is rejected, not deduped", len(rejected) == 1 and len(deduped) == 0)
scored = [item("x" * 300, "ai", "low.pdf", score=MIN_RAW_SCORE - 1)]
kept, rejected, deduped = _filter_and_dedup(scored)
check("below-floor score is rejected, not deduped", len(rejected) == 1 and len(deduped) == 0)

print("\n[_shingles/_near_dup basic sanity]")
check("identical text is a near-dup of itself", _near_dup("hello world " * 20, "hello world " * 20))
check("empty text is never a near-dup", not _near_dup("", "hello world " * 20))
check("completely different text is not a near-dup", not _near_dup(REAL_TEXT, DISTINCT_TEXT))

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
