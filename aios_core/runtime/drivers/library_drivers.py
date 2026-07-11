"""
Python drivers for the library skills that have deterministic reference
implementations (wrapping second_brain/). Generative skills
(concept_distillation, hypothesis_generation) stay agent-type — reasoning
enters via adapters, never via the runtime.

All drivers: fn(inputs: dict, context: dict) -> output dict.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent   # repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_INDEX = ROOT / "memory" / "index" / "chunks.json"


# ── book_ingestion (v1.1: per-corpus indexes) ──────────────────────────────
def run_ingest(inputs: dict, context: dict) -> dict:
    if inputs.get("corpus_id"):
        from second_brain import corpus_manager as cm
        r = cm.ingest_corpus(inputs["corpus_id"])
        return {"files": r["files"], "chunks": r["chunks"],
                "index_path": cm.get(inputs["corpus_id"])["index_path"]}
    from second_brain.ingest import ingest
    result = ingest(inputs["source_dir"],
                    tuple(inputs.get("extensions", [".md", ".txt"])),
                    index_path=inputs.get("index_path"))
    if "error" in result:
        raise ValueError(result["error"])
    return {"files": result["files"], "chunks": result["chunks"],
            "index_path": result["index"]}


# ── retrieve_context v2 — ALL retrieval goes through the Gateway ──────────
def run_retrieve(inputs: dict, context: dict) -> dict:
    from second_brain.gateway import retrieve
    return retrieve(inputs["query"],
                    mission_id=inputs.get("mission_id"),
                    corpora=inputs.get("corpora"),
                    cross_corpus=inputs.get("cross_corpus"),
                    top_k=min(int(inputs.get("top_k", 5)), 5))


# ── rag_search v2 (gateway-scoped; generative answer via agent_adapter) ───
def run_rag_search(inputs: dict, context: dict) -> dict:
    from second_brain.gateway import retrieve
    r = retrieve(inputs["question"],
                 mission_id=inputs.get("mission_id"),
                 corpora=inputs.get("corpora"),
                 cross_corpus=inputs.get("cross_corpus"),
                 top_k=int(inputs.get("top_k", 4)))
    hits = r["hits"]
    if not hits:
        return {"answer": None, "found": False, "citations": [],
                "scope": r["scope"], "note": "not found in corpus scope"}
    adapter = context.get("agent_adapter")
    if adapter:
        answer = adapter({"id": "rag_search"}, {"question": inputs["question"],
                                                "context_chunks": hits}, context)
        text = answer.get("answer", "") if isinstance(answer, dict) else str(answer)
    else:
        # extractive fallback: best chunk verbatim — grounded by construction
        text = hits[0]["text"][:800]
    return {"answer": text, "found": True, "scope": r["scope"],
            "widened": r["widened"],
            "citations": [{"source": h["source"], "corpus": h["corpus"],
                           "confidence": h["confidence"],
                           "cross_corpus": h["cross_corpus"]} for h in hits]}


# ── evidence_validation (claim-level, deterministic — critic's scoring) ───
def run_validate_claim(inputs: dict, context: dict) -> dict:
    from second_brain.retrieve import Retriever
    r = Retriever(Path(inputs.get("index_path") or DEFAULT_INDEX))
    hits = r.retrieve(inputs["statement"], top_k=5)
    best = hits[0]["score"] if hits else 0.0
    hit_sources = {h["source"] for h in hits}
    claimed = inputs.get("claimed_sources", [])
    checkable = [s for s in claimed if s.endswith(".md")]
    confirmed = [s for s in checkable if s in hit_sources]
    corroboration = len(confirmed) / len(checkable) if checkable else 0.0
    confidence = round(0.5 * min(1.0, best / 0.35) + 0.5 * corroboration, 2)
    flags = [f"claimed source not in top-5 evidence: {s}"
             for s in checkable if s not in hit_sources]
    flags += [f"non-index provenance (cannot verify by retrieval): {s}"
              for s in claimed if not s.endswith(".md")]
    status = ("supported" if confidence >= 0.6 else
              "partial" if confidence >= 0.3 else "unsupported")
    return {"confidence": confidence, "status": status, "flags": flags,
            "evidence": [{"source": h["source"], "score": h["score"]} for h in hits[:3]]}


# ── critic (store-wide review, wraps second_brain/critic.py) ──────────────
def run_critic(inputs: dict, context: dict) -> dict:
    from second_brain.critic import criticize
    return criticize()


# ── evaluator (deterministic check runner) ─────────────────────────────────
def run_evaluator(inputs: dict, context: dict) -> dict:
    results = []
    for c in inputs["checks"]:
        try:
            r = subprocess.run(c["cmd"], shell=True, capture_output=True,
                               timeout=int(inputs.get("timeout_s", 120)),
                               cwd=inputs.get("cwd") or str(ROOT))
            results.append({"id": c["id"], "passed": r.returncode == 0,
                            "detail": (r.stdout or r.stderr)[-200:].decode(errors="ignore").strip()})
        except Exception as e:
            results.append({"id": c["id"], "passed": False, "detail": str(e)})
    return {"results": results, "all_pass": all(x["passed"] for x in results)}


# ── memory_compression (M6 compliance audit over a memory root) ───────────
def run_compression_audit(inputs: dict, context: dict) -> dict:
    root = Path(inputs["memory_root"]).expanduser()
    max_lines = int(inputs.get("max_lines", 200))
    issues = []
    for f in sorted(root.glob("*.md")):
        lines = f.read_text().splitlines()
        if len(lines) > max_lines:
            issues.append(f"{f.name}: {len(lines)} lines > {max_lines}")
        if f.name == "log.md":
            for ln in lines:
                if ln.startswith("- ") and len(ln) > 250:
                    issues.append(f"log.md entry exceeds one-line budget: {ln[:60]}...")
    # separation-of-concerns spot check: numbered PLAN items (e.g. "- [ ] 2.1 ...")
    # don't belong in state.md (criteria checklists are state and are fine)
    state = root / "state.md"
    if state.exists() and re.search(r"^- \[ \] \d+\.\d+", state.read_text(), re.M):
        issues.append("state.md contains numbered plan items (plans belong in plan.md)")
    return {"compliant": not issues, "issues": issues,
            "files_audited": len(list(root.glob('*.md')))}
