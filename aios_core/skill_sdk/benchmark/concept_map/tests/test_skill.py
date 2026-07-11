"""Tests for the RECREATED concept_map (SDK benchmark). Standalone, idempotent."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from aios_core.skill_sdk.benchmark.concept_map.driver import run

FAILURES = []
def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond: FAILURES.append(name)

def test_E1_fixture():
    fx = {"concepts": {
        "A": {"confidence": 0.9, "verification": {"status": "supported"},
              "relationships": [{"to": "B", "type": "complements"}, {"to": "C", "type": "explains"}]},
        "B": {"confidence": 0.7, "verification": {"status": "supported"}, "relationships": []},
        "C": {"confidence": 0.2, "verification": {"status": "unsupported"}, "relationships": []}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(fx, f); p = f.name
    out = run({"min_confidence": 0.6, "store_path": p}, {})
    check("E1 nodes = A,B (C filtered)", [n["name"] for n in out["nodes"]] == ["A", "B"])
    check("E1 edge A->B kept, A->C dropped (dangling)", out["edges"] == [{"from": "A", "to": "B", "type": "complements"}])
    Path(p).unlink()

def test_E2_negative():
    out = run({"name_contains": "zzqxv-flurbo"}, {})
    check("E2 nonsense filter -> empty graph", out == {"nodes": [], "edges": [], "n": 0})
    out2 = run({"store_path": "/nonexistent/store.json"}, {})
    check("E2 absent store -> empty graph, no raise", out2["n"] == 0)

def test_E3_invariants_live():
    for floor in (0.0, 0.6, 0.95):
        out = run({"min_confidence": floor}, {})
        names = {n["name"] for n in out["nodes"]}
        check(f"E3 no dangling edges @ {floor}",
              all(e["from"] in names and e["to"] in names for e in out["edges"]))
        check(f"E3 n==len(nodes) @ {floor}", out["n"] == len(out["nodes"]))
        check(f"E3 confidences in [0,1] @ {floor}",
              all(0 <= n["confidence"] <= 1 for n in out["nodes"]))

def test_examples_replay():
    exdir = Path(__file__).resolve().parents[1] / "examples"
    for ex in sorted(exdir.glob("*.json")):
        e = json.loads(ex.read_text())
        out = run(e["inputs"], {})
        if e.get("expected_output") is not None:
            check(f"example {ex.name} exact", out == e["expected_output"], str(out)[:80])
        else:
            check(f"example {ex.name} invariants", out["n"] == len(out["nodes"]))

if __name__ == "__main__":
    test_E1_fixture(); test_E2_negative(); test_E3_invariants_live(); test_examples_replay()
    print("=" * 50)
    if FAILURES: print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS")
