"""
AIOS Core SDK — Retrieval API (stable).

The single retrieval entry point. Scope is NEVER guessed (PROJECT_CHARTER.md
P9): pass a mission (its declared corpora) or explicit corpora. Wraps the
Retrieval Gateway + Corpus Manager (second_brain), so applications depend only
on this stable surface, not on gateway internals.

    from aios_core import retrieval
    hits = retrieval.retrieve("kelly criterion", mission="build-ai-stock-...")
    hits = retrieval.retrieve("agent memory", corpora=["ai-books"])
"""
from __future__ import annotations

import sys
from pathlib import Path

# second_brain lives at repo root; ensure importable regardless of caller cwd.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from second_brain.gateway import retrieve as _retrieve, NoScopeError  # noqa: E402
from second_brain import corpus_manager as _cm                        # noqa: E402

__all__ = ["retrieve", "NoScopeError", "list_corpora", "get_corpus",
           "register_corpus", "ingest_corpus", "adopt_index"]


def retrieve(query: str, mission: str | None = None, corpora: list[str] | None = None,
             cross_corpus: bool | None = None, top_k: int = 5) -> dict:
    """Corpus-scoped retrieval with provenance. `mission` = a mission slug whose
    declared corpora define scope; `corpora` = explicit override. One of the two
    is required (NoScopeError otherwise). Returns {hits[], n, scope, widened,
    confidence}; each hit carries corpus[], confidence, cross_corpus."""
    return _retrieve(query, mission_id=mission, corpora=corpora,
                     cross_corpus=cross_corpus, top_k=top_k)


# ── Corpus management ──────────────────────────────────────────────────────
def list_corpora() -> list[dict]:
    return _cm.list_corpora()


def get_corpus(corpus_id: str) -> dict:
    return _cm.get(corpus_id)


def register_corpus(corpus: dict) -> dict:
    return _cm.register(corpus)


def ingest_corpus(corpus_id: str) -> dict:
    return _cm.ingest_corpus(corpus_id)


def adopt_index(corpus_id: str, existing_index) -> dict:
    return _cm.adopt_index(corpus_id, existing_index)
