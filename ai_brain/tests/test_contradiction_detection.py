"""Offline regression test for structured contradiction detection (the
evidence-driven upgrade's Phase 1b): evidence_engine()'s conflicts[] shape
changed from a flat list of strings to structured
{sources, disagreement, why_differ, better_supported, remains_uncertain}
objects, and professor_engine's rendering of them.

    python3 tests/test_contradiction_detection.py

No network, no API key: _normalize_conflict/_format_conflicts are pure
functions, and evidence_engine's no-material fallback path needs no LLM call.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import (_normalize_conflict, _format_conflicts, evidence_engine,
                      _CONFLICT_FIELDS)

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


class _Budget:
    def __init__(self):
        self.by_stage = {}
    def record(self, stage, model, usage, secs):
        self.by_stage[stage] = {"model": model}


print("[_normalize_conflict: well-formed entry passes through with all 5 fields]")
well_formed = {"sources": ["S1", "S3"], "disagreement": "whether X causes Y",
               "why_differ": "different assumptions", "better_supported": "S1, more recent",
               "remains_uncertain": "long-run effect size"}
out = _normalize_conflict(well_formed)
check("all 5 fields present", all(k in out for k in _CONFLICT_FIELDS))
check("values preserved unchanged", out == well_formed)

print("\n[_normalize_conflict: missing fields default to empty, never crash]")
sparse = {"sources": ["S1", "S2"], "disagreement": "whether X causes Y"}
out2 = _normalize_conflict(sparse)
check("missing why_differ defaults to empty string", out2["why_differ"] == "")
check("missing better_supported defaults to empty string", out2["better_supported"] == "")
check("missing remains_uncertain defaults to empty string", out2["remains_uncertain"] == "")
check("sources preserved", out2["sources"] == ["S1", "S2"])

print("\n[_normalize_conflict: a bare string (old flat-list shape, or a non-compliant model) never crashes]")
out3 = _normalize_conflict("S1 and S3 disagree about the learning rate")
check("bare string becomes the disagreement field, empty sources",
      out3["sources"] == [] and out3["disagreement"] == "S1 and S3 disagree about the learning rate")
check("all 5 fields still present for a bare-string input", all(k in out3 for k in _CONFLICT_FIELDS))

print("\n[_normalize_conflict: missing 'sources' key entirely defaults to empty list, not a crash]")
no_sources = {"disagreement": "x"}
out4 = _normalize_conflict(no_sources)
check("missing sources key -> empty list, not KeyError", out4["sources"] == [])

print("\n[_format_conflicts: renders legibly, not a raw Python repr]")
rendered = _format_conflicts([well_formed])
check("mentions the disagreement", "whether X causes Y" in rendered)
check("mentions why they differ", "different assumptions" in rendered)
check("mentions which is better supported", "S1, more recent" in rendered)
check("mentions what remains uncertain", "long-run effect size" in rendered)
check("does not render as a raw dict repr", "{'sources'" not in rendered and "why_differ':" not in rendered)

print("\n[_format_conflicts: empty list renders to nothing, no stray header]")
check("no conflicts -> empty string", _format_conflicts([]) == "")

print("\n[_format_conflicts: missing optional fields degrade to a readable placeholder, not blank]")
sparse_rendered = _format_conflicts([out2])
check("empty why_differ shows a placeholder, not a blank line",
      "why they differ: unstated" in sparse_rendered)
check("empty better_supported shows a placeholder",
      "better supported: unclear" in sparse_rendered)

print("\n[evidence_engine: skipped/no-material fallback paths produce the NEW empty shape]")
skipped = evidence_engine("q", {"kept": []}, {"hits": []}, None, "intro", None, _Budget())
check("intro-depth skip: conflicts is an empty list (new shape), not omitted",
      skipped.get("conflicts") == [])
no_material = evidence_engine("q", {"kept": []}, {"hits": []}, None, "intermediate", None, _Budget())
check("no material at all: conflicts is an empty list (new shape)",
      no_material.get("conflicts") == [])

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
