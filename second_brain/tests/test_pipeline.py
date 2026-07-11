"""
Second Brain — Pipeline Validation Suite
Tests every stage: ingest → retrieve → concept store → critic → loop.
Writes memory/validation_report.md.

Run: python3 second_brain/tests/test_pipeline.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, str, bool, str]] = []   # (stage, test, passed, detail)


def check(stage: str, name: str, cond: bool, detail: str = ""):
    RESULTS.append((stage, name, bool(cond), detail))
    print(f"  [{'OK' if cond else 'FAIL'}] {stage}: {name}  {detail}")


# ── Stage 1: ingest ────────────────────────────────────────────────────────
def test_ingest():
    from second_brain.ingest import _chunk, ingest
    # chunking: respects size, loses no text
    text = "\n\n".join(f"para {i} " + "x" * 300 for i in range(10))
    chunks = _chunk(text, size=1200)
    check("ingest", "chunks stay near size limit", all(len(c) <= 1500 for c in chunks),
          f"max={max(len(c) for c in chunks)}")
    joined = " ".join(chunks)
    check("ingest", "no paragraph lost in chunking",
          all(f"para {i}" in joined for i in range(10)))
    # live index exists and is well-formed
    idx = json.loads((ROOT / "memory/index/chunks.json").read_text())
    check("ingest", "index well-formed (files>0, chunks>0)",
          idx["n_files"] > 0 and len(idx["chunks"]) > 0,
          f"{idx['n_files']} files / {len(idx['chunks'])} chunks")
    check("ingest", "every chunk has source+text keys",
          all("source" in c and "text" in c for c in idx["chunks"]))


# ── Stage 2: retrieve ──────────────────────────────────────────────────────
def test_retrieve():
    from second_brain.retrieve import Retriever
    r = Retriever()
    hits = r.retrieve("agent design patterns", top_k=3)
    check("retrieve", "returns results for known topic", len(hits) > 0)
    check("retrieve", "results ranked descending",
          all(hits[i]["score"] >= hits[i+1]["score"] for i in range(len(hits)-1)))
    check("retrieve", "top hit topically correct",
          "agentic" in hits[0]["source"] if hits else False, hits[0]["source"] if hits else "")
    check("retrieve", "gibberish query returns empty (no false positives)",
          len(r.retrieve("zzqxv wvvptk qqrst", top_k=3)) == 0)


# ── Stage 3: concept store ─────────────────────────────────────────────────
def test_concept_store():
    from second_brain import concept_store as cs
    data = cs.load()
    concepts = data["concepts"]
    check("store", "≥10 concepts migrated", len(concepts) >= 10, f"n={len(concepts)}")
    required = {"name", "principle", "when_to_use", "sources", "confidence",
                "verification", "relationships", "created", "updated"}
    check("store", "all concepts carry full schema",
          all(required <= set(c.keys()) for c in concepts.values()))
    n_rels = sum(len(c["relationships"]) for c in concepts.values())
    check("store", "relationship graph non-empty", n_rels >= 5, f"edges={n_rels}")
    check("store", "all relationship targets exist (no dangling edges)",
          all(r["to"] in concepts for c in concepts.values() for r in c["relationships"]))
    # round-trip: upsert preserves verification
    before = concepts["RAG Maturity Ladder"]["confidence"]
    cs.upsert({"name": "RAG Maturity Ladder",
               "principle": concepts["RAG Maturity Ladder"]["principle"],
               "when_to_use": concepts["RAG Maturity Ladder"]["when_to_use"],
               "sources": concepts["RAG Maturity Ladder"]["sources"]})
    after = cs.load()["concepts"]["RAG Maturity Ladder"]["confidence"]
    check("store", "upsert preserves critic verdict (no silent reset)", before == after)


# ── Stage 4: critic ────────────────────────────────────────────────────────
def test_critic():
    from second_brain import concept_store as cs
    concepts = cs.load()["concepts"]
    check("critic", "every concept has confidence in [0,1]",
          all(c["confidence"] is not None and 0 <= c["confidence"] <= 1
              for c in concepts.values()))
    check("critic", "every concept has a verification status",
          all(c["verification"]["status"] in
              ("supported", "partial", "unsupported", "unverified")
              for c in concepts.values()))
    # discrimination: scores must not be uniform (a critic that says 1.0 to
    # everything verifies nothing)
    scores = {c["confidence"] for c in concepts.values()}
    check("critic", "scores discriminate (not all identical)", len(scores) > 1,
          f"distinct={sorted(scores)}")
    # unverifiable provenance must be flagged, not silently accepted
    flagged = [n for n, c in concepts.items()
               if any("non-index provenance" in f or "workspace" in f.lower()
                      for f in c["verification"]["flags"])]
    check("critic", "non-index provenance flagged", len(flagged) >= 1,
          f"{len(flagged)} concept(s)")
    check("critic", "report file exists", (ROOT / "memory/critic_report.md").exists())


# ── Stage 5: loop ──────────────────────────────────────────────────────────
def test_loop():
    from second_brain.loop import check as loop_check
    r = loop_check()
    check("loop", "stability check runs and reports all stages",
          {"ingest", "retrieval", "distill", "stable"} <= set(r.keys()))
    check("loop", "system currently STABLE", r["stable"], json.dumps(
        {k: v for k, v in r.items() if k != "stable"}))


# ── Report ─────────────────────────────────────────────────────────────────
def write_report():
    n_pass = sum(1 for *_, p, _ in [(a, b, c, d) for a, b, c, d in RESULTS] if p)
    lines = [
        "# validation_report.md — Pipeline Validation",
        f"<!-- Generated {date.today().isoformat()} by second_brain/tests/test_pipeline.py. Overwritten each run. -->",
        "",
        f"**Result: {n_pass}/{len(RESULTS)} pass**",
        "",
        "| stage | test | result | detail |",
        "|---|---|---|---|",
    ]
    for stage, name, passed, detail in RESULTS:
        lines.append(f"| {stage} | {name} | {'PASS' if passed else 'FAIL'} | {detail} |")
    (ROOT / "memory" / "validation_report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    test_ingest()
    test_retrieve()
    test_concept_store()
    test_critic()
    test_loop()
    write_report()
    failures = [(s, n) for s, n, p, _ in RESULTS if not p]
    print(f"\n{'='*60}\n{'ALL PASS' if not failures else f'FAILURES: {failures}'}"
          f"  ({len(RESULTS) - len(failures)}/{len(RESULTS)})")
    sys.exit(1 if failures else 0)
