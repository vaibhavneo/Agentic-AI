"""Recreated from contract docs ONLY (SKILL_SDK benchmark, Part 10).
Spec: nodes {name, confidence, status} filtered by min_confidence /
name_contains (case-insensitive substring per 'contains'); edges keep only
pairs whose BOTH endpoints survive; empty/absent store -> empty graph.
Ordering: contract says 'Deterministic' without naming an order -> chose
sorted-by-name (recorded as spec gap G1 in BENCHMARK_REPORT.md)."""
from __future__ import annotations
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_STORE = _ROOT / "memory" / "concepts.json"


def run(inputs: dict, context: dict) -> dict:
    store = Path(inputs.get("store_path") or _DEFAULT_STORE)
    concepts = {}
    if store.exists():
        concepts = json.loads(store.read_text()).get("concepts", {})
    min_conf = float(inputs.get("min_confidence", 0.0) or 0.0)
    needle = (inputs.get("name_contains") or "").lower()

    keep = {}
    for name, c in concepts.items():
        conf = c.get("confidence") or 0.0
        if conf < min_conf or (needle and needle not in name.lower()):
            continue
        keep[name] = {"name": name, "confidence": conf,
                      "status": c.get("verification", {}).get("status", "unverified")}

    edges = [{"from": n, "to": r["to"], "type": r["type"]}
             for n in sorted(keep)
             for r in concepts[n].get("relationships", [])
             if r["to"] in keep]
    nodes = sorted(keep.values(), key=lambda x: x["name"])
    return {"nodes": nodes, "edges": edges, "n": len(nodes)}
