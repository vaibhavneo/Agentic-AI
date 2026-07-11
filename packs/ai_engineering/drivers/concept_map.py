"""
Driver for the AI Engineering pack's `concept_map` skill.

Deterministic (PROJECT_CHARTER.md P6): reads the verified concept store
(memory/concepts.json — the source of truth per D9) and returns a graph of
concepts and their typed relationships. No LLM, no priors. A pack skill that
adds capability to the platform WITHOUT touching AIOS Core.
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS = _ROOT / "memory" / "concepts.json"


def run(inputs: dict, context: dict) -> dict:
    min_conf = float(inputs.get("min_confidence", 0.0) or 0.0)
    needle = (inputs.get("name_contains") or "").lower()

    data = json.loads(_CONCEPTS.read_text()) if _CONCEPTS.exists() else {"concepts": {}}
    concepts = data.get("concepts", {})

    nodes = []
    keep: set[str] = set()
    for name, c in concepts.items():
        conf = c.get("confidence") or 0.0
        if conf < min_conf:
            continue
        if needle and needle not in name.lower():
            continue
        keep.add(name)
        nodes.append({
            "name": name,
            "confidence": conf,
            "status": c.get("verification", {}).get("status", "unverified"),
        })

    edges = []
    for name in keep:
        for rel in concepts[name].get("relationships", []):
            # keep an edge only if both endpoints survived the filter (a real,
            # navigable sub-graph — no dangling edges)
            if rel["to"] in keep:
                edges.append({"from": name, "to": rel["to"], "type": rel["type"]})

    return {"nodes": sorted(nodes, key=lambda x: -x["confidence"]),
            "edges": edges, "n": len(nodes)}
