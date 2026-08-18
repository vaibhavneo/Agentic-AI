"""Offline regression test for the off-topic filtering fix (Milestone 6).

    python3 tests/test_off_topic_filter.py

No network, no API key: _filter_off_topic() is pure. This is the fix for a
real bug the new eval suite caught live: a question about Neapolitan pizza
BM25-matched a Python tutorial's `pizza = {...}` dict and a RAG demo's test
query, both of which cleared the score/length/frontmatter quality filters
(they're real, well-formed prose genuinely containing those words) and were
correctly flagged off_topic by evidence_engine — but off_topic had existed
as a purely informational field since before this session started, so
professor_engine wove the incidental tutorial examples into a confident,
citation-backed-looking answer about actual pizza anyway.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import _filter_off_topic

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


def kept(tags):
    return {"kept": [{"tag": t, "text": f"text for {t}", "source": f"{t}.pdf"} for t in tags],
            "available": True, "evidence_strength": "usable", "top_score": 20.0}


print("[no off_topic tags — returns the same object, no needless copy]")
be = kept(["S1", "S2"])
out = _filter_off_topic(be, [])
check("identical object returned when there's nothing to filter", out is be)
out2 = _filter_off_topic(be, None)
check("None off_topic_tags treated the same as empty", out2 is be)

print("\n[a flagged tag is excluded from kept]")
be2 = kept(["S1", "S2", "S3"])
out3 = _filter_off_topic(be2, ["S2"])
check("S2 excluded", [c["tag"] for c in out3["kept"]] == ["S1", "S3"],
      str([c["tag"] for c in out3["kept"]]))
check("original book_ev is untouched — evidence panel can still show everything",
      [c["tag"] for c in be2["kept"]] == ["S1", "S2", "S3"])
check("other fields (evidence_strength, top_score) pass through unchanged",
      out3["evidence_strength"] == "usable" and out3["top_score"] == 20.0)

print("\n[the exact real bug: pizza-tutorial passages flagged off-topic]")
pizza_case = kept(["S1", "S2", "S3", "S4", "S5"])
# S1/S2 = Python tutorial's `pizza = {...}` dict + a RAG demo's test query,
# both real evidence_engine would flag off_topic for an actual pizza question.
filtered = _filter_off_topic(pizza_case, ["S1", "S2"])
check("the two off-topic tutorial passages are excluded",
      "S1" not in [c["tag"] for c in filtered["kept"]] and
      "S2" not in [c["tag"] for c in filtered["kept"]])
check("the three genuinely-relevant passages survive",
      [c["tag"] for c in filtered["kept"]] == ["S3", "S4", "S5"])

print("\n[all kept items flagged off-topic — kept becomes empty, not an error]")
be3 = kept(["S1", "S2"])
out4 = _filter_off_topic(be3, ["S1", "S2"])
check("kept is empty", out4["kept"] == [])
check("this correctly flips honesty.grounded_in_library to False downstream "
      "(bool(book_ev.get('kept')) on an empty list)", bool(out4.get("kept")) is False)

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
