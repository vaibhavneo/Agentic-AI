"""
Retrieval Gateway (AIOS P0.2) — the ONLY retrieval entry point.
Skills call retrieve(query, mission_id=...) — never an index name.

Pipeline (architecture §6.5.3):
  SCOPE → FAN-OUT → NORMALIZE → MERGE+RANK → DEDUP → CONFIDENCE →
  PROVENANCE → (optional) CROSS-CORPUS widening
"""
from __future__ import annotations

import json
from pathlib import Path

from second_brain.retrieve import Retriever
from second_brain import corpus_manager as cm

ROOT = Path(__file__).parent.parent
MISSIONS_DIR = ROOT / "memory" / "missions"

_retrievers: dict[str, Retriever] = {}     # per-corpus cache (index load is the cost)


class NoScopeError(ValueError):
    """Raised when neither a mission nor an explicit corpora override supplies
    scope. Scope is never guessed (architecture §6.5.3 step 1)."""


def _get_retriever(corpus_id: str) -> Retriever | None:
    if corpus_id in _retrievers:
        return _retrievers[corpus_id]
    c = cm.get(corpus_id)
    idx = Path(c["index_path"])
    if not idx.exists() or c["stats"]["chunks"] == 0:
        return None                       # registered but not ingested
    r = Retriever(idx)
    _retrievers[corpus_id] = r
    return r


def _mission_scope(mission_id: str) -> tuple[list[str], bool]:
    mf = MISSIONS_DIR / mission_id / "mission.json"
    if not mf.exists():
        raise KeyError(f"unknown mission: {mission_id}")
    m = json.loads(mf.read_text())
    return m.get("corpora", []), bool(m.get("cross_corpus", False))


def _shingles(text: str, n: int = 8) -> set[str]:
    words = text.lower().split()
    return {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def _near_dup(a: str, b: str, threshold: float = 0.8) -> bool:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= threshold


def _query_corpora(query: str, corpus_ids: list[str], top_k: int,
                   cross_flag: bool) -> list[dict]:
    hits = []
    for cid in corpus_ids:
        r = _get_retriever(cid)
        if r is None:
            continue
        raw = r.retrieve(query, top_k=top_k)
        if not raw:
            continue
        # NORMALIZE: raw TF-IDF scores are not comparable across corpora
        # (different df distributions) — min-max per corpus, × reliability
        reliability = cm.get(cid).get("reliability", 1.0)
        max_s = max(h["score"] for h in raw)
        min_s = min(h["score"] for h in raw)
        span = (max_s - min_s) or 1.0
        for h in raw:
            norm = (h["score"] - min_s) / span if len(raw) > 1 else 1.0
            hits.append({
                "text": h["text"], "source": h["source"],
                "corpus": [cid],
                "raw_score": h["score"],
                "normalized_score": round(norm, 4),
                "confidence": round(norm * reliability, 4),
                "cross_corpus": cross_flag,
                "chunk_id": h.get("chunk_id"),
            })
    return hits


def retrieve(query: str, mission_id: str | None = None, top_k: int = 5,
             corpora: list[str] | None = None,
             cross_corpus: bool | None = None) -> dict:
    # 1. SCOPE
    if corpora:
        scope, allow_cross = list(corpora), bool(cross_corpus)
        scope_kind = "override"
    elif mission_id:
        scope, allow_cross = _mission_scope(mission_id)
        if cross_corpus is not None:
            allow_cross = cross_corpus
        scope_kind = "mission"
    else:
        raise NoScopeError(
            "retrieval requires a mission_id or an explicit corpora override — "
            "scope is never guessed")

    # 2-3. FAN-OUT + NORMALIZE (+ confidence per hit)
    hits = _query_corpora(query, scope, top_k, cross_flag=False)

    # 8. CROSS-CORPUS widening (before final rank so widened hits compete)
    widened = False
    if len(hits) < top_k and allow_cross:
        others = [c["id"] for c in cm.list_corpora() if c["id"] not in scope]
        extra = _query_corpora(query, others, top_k, cross_flag=True)
        if extra:
            hits += extra
            widened = True

    # 4. MERGE + RANK
    hits.sort(key=lambda h: h["confidence"], reverse=True)

    # 5. DEDUP — near-duplicates collapse; survivor keeps BOTH provenances
    deduped: list[dict] = []
    for h in hits:
        dup = next((d for d in deduped if _near_dup(h["text"], d["text"])), None)
        if dup:
            for cid in h["corpus"]:
                if cid not in dup["corpus"]:
                    dup["corpus"].append(cid)
            continue
        deduped.append(h)

    final = deduped[:top_k]
    return {
        "hits": final,
        "n": len(final),
        "scope": scope,
        "scope_kind": scope_kind,
        "widened": widened,
        "confidence": max((h["confidence"] for h in final), default=0.0),
    }
