"""
Second Brain MVP — Recursive Loop (Phase 4)
File-driven stability check: reads the criteria state from artifacts (not chat
memory), reports which phase is weakest, exits 0 when stable.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
INDEX = ROOT / "memory" / "index" / "chunks.json"
CACHE = ROOT / "memory" / "knowledge_cache.md"


def check() -> dict:
    sys.path.insert(0, str(ROOT))
    results = {}

    # 1. ingest ran without error
    try:
        data = json.loads(INDEX.read_text())
        results["ingest"] = data.get("n_files", 0) > 0 and len(data.get("chunks", [])) > 0
    except Exception:
        results["ingest"] = False

    # 2. retrieval returns relevant chunks for 3 test queries
    try:
        from second_brain.retrieve import Retriever
        r = Retriever()
        queries = ["agent design patterns", "retrieval augmented generation",
                   "memory context window"]
        results["retrieval"] = all(len(r.retrieve(q, top_k=3)) > 0 for q in queries)
    except Exception:
        results["retrieval"] = False

    # 3. >=3 concepts in the structured store (concepts.json is source of
    #    truth since the critic upgrade; knowledge_cache.md is a rendered view)
    try:
        store = json.loads((ROOT / "memory" / "concepts.json").read_text())
        n_models = len(store.get("concepts", {}))
        results["distill"] = n_models >= 3
        results["n_models"] = n_models
    except Exception:
        # fallback: legacy markdown count
        try:
            n_models = len(re.findall(r"^## ", CACHE.read_text(), re.M))
            results["distill"] = n_models >= 3
            results["n_models"] = n_models
        except Exception:
            results["distill"] = False
            results["n_models"] = 0

    results["stable"] = results["ingest"] and results["retrieval"] and results["distill"]
    return results


if __name__ == "__main__":
    r = check()
    print(json.dumps(r, indent=2))
    if not r["stable"]:
        weakest = next(k for k in ("ingest", "retrieval", "distill") if not r[k])
        print(f"NEXT: fix phase '{weakest}'")
        sys.exit(1)
    print("STATUS: STABLE")
