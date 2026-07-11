"""
Second Brain — Critic Agent
Verifies every concept in the store against retrieved evidence (retrieve-
before-reasoning: the verdict is computed FROM retrieval results, never from
the critic's own priors).

Confidence model (deterministic, reproducible):
  retrieval_support  = best TF-IDF score for (name + principle) query, squashed to 0-1
  source_corroboration = fraction of the concept's CLAIMED sources that actually
                         appear in the top-k retrieved evidence
  confidence = 0.5 * squash(retrieval_support) + 0.5 * source_corroboration

Status: supported (>=0.6) | partial (>=0.3) | unsupported (<0.3)
Flags: claimed sources not found in evidence; non-index provenance (e.g.
"workspace experience") which retrieval structurally cannot confirm.

Writes results into concepts.json and memory/critic_report.md.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from second_brain.retrieve import Retriever
from second_brain import concept_store

REPORT = ROOT / "memory" / "critic_report.md"
TOP_K = 5


def _squash(score: float) -> float:
    """TF-IDF scores here live roughly in 0-0.5; map to 0-1 with soft ceiling."""
    return min(1.0, score / 0.35)


def _src_name(s) -> str:
    """Sources may be legacy strings or structured {corpus, source} (AIOS §6.5.4)."""
    return s["source"] if isinstance(s, dict) else s


def _src_corpus(s) -> str:
    return s.get("corpus", "curated-wiki") if isinstance(s, dict) else "curated-wiki"


def _is_index_source(src) -> bool:
    """A source the retriever can possibly confirm (a file in an index corpus)."""
    name = _src_name(src)
    return name.endswith(".md") and "(" not in name and _src_corpus(src) != "workspace"


def criticize() -> dict:
    r = Retriever()
    data = concept_store.load()
    rows = []

    for name, c in data["concepts"].items():
        query = f"{name} {c['principle']}"
        hits = r.retrieve(query, top_k=TOP_K)
        best = hits[0]["score"] if hits else 0.0
        hit_sources = {h["source"] for h in hits}

        claimed = c.get("sources", [])
        checkable = [s for s in claimed if _is_index_source(s)]
        confirmed = [s for s in checkable if _src_name(s) in hit_sources]

        corroboration = len(confirmed) / len(checkable) if checkable else 0.0
        confidence = round(0.5 * _squash(best) + 0.5 * corroboration, 2)

        flags = []
        for s in claimed:
            label = f"{_src_corpus(s)}:{_src_name(s)}"
            if not _is_index_source(s):
                flags.append(f"non-index provenance (cannot verify by retrieval): {label}")
            elif _src_name(s) not in hit_sources:
                flags.append(f"claimed source not in top-{TOP_K} evidence: {label}")
        if not hits:
            flags.append("no retrieval evidence found at all")

        status = ("supported" if confidence >= 0.6 else
                  "partial" if confidence >= 0.3 else "unsupported")

        c["confidence"] = confidence
        c["verification"] = {
            "status": status,
            "evidence": [{"source": h["source"], "score": h["score"]} for h in hits[:3]],
            "flags": flags,
        }
        rows.append((name, confidence, status, len(flags)))

    concept_store.save(data)
    _write_report(rows, data)
    return {"n": len(rows),
            "supported": sum(1 for _, _, s, _ in rows if s == "supported"),
            "partial": sum(1 for _, _, s, _ in rows if s == "partial"),
            "unsupported": sum(1 for _, _, s, _ in rows if s == "unsupported")}


def _write_report(rows, data) -> None:
    lines = [
        "# critic_report.md — Evidence Verification",
        f"<!-- Generated {date.today().isoformat()} by second_brain/critic.py. Overwritten each run. -->",
        "",
        "| concept | confidence | status | flags |",
        "|---|---|---|---|",
    ]
    for name, conf, status, nflags in sorted(rows, key=lambda x: -x[1]):
        lines.append(f"| {name} | {conf:.2f} | {status} | {nflags} |")
    lines.append("")
    lines.append("## Flag detail")
    for name, c in data["concepts"].items():
        for f in c["verification"]["flags"]:
            lines.append(f"- **{name}**: {f}")
    lines.append("")
    lines.append("Method: confidence = 0.5·retrieval_support + 0.5·source_corroboration "
                 "(deterministic; see critic.py docstring). 'partial' usually means the "
                 "principle generalizes beyond what the small curated index can confirm — "
                 "a signal to ingest more sources, not necessarily a wrong claim.")
    REPORT.write_text("\n".join(lines))


if __name__ == "__main__":
    import json
    print(json.dumps(criticize(), indent=2))
