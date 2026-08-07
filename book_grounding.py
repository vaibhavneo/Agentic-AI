"""
Phase 9 — book-corpus grounding for /api/chat. Retrieves real chunks from the
already-ingested 23-book knowledge base (knowledge/ingest.py, TF-IDF over
10k+ page-tagged chunks — no new ingestion pipeline needed, it already
existed and was already used for the full-reading feature, just not for
chat) and formats them with an explicit (Book Title, page N) citation per
passage, so the system prompt can tell the model to cite passages "exactly
as shown" and never has to let it invent a title or page number: every
citation available to it in context is real.
"""
from __future__ import annotations

from typing import Optional


def build_query(question: str, topics: list[str], bundle: Optional[dict], division: str) -> str:
    """Combine the raw question with detected topics and chart context
    (ascendant sign, division in play) into a retrieval query — the same
    kind of query-enrichment already used for the streaming reading feature
    in web/app.py's book_ctx()."""
    parts = [question] + list(topics)
    if bundle:
        d1 = bundle.get("divisional_charts", {}).get("D1", {})
        asc = (d1.get("ascendant") or {}).get("sign")
        if asc:
            parts.append(f"{asc} ascendant")
        if division and division != "D1":
            parts.append(division)
    return " ".join(parts)


def _format_passages(results: list[dict], max_chars: int) -> str:
    parts = []
    total = 0
    for r in results:
        src = r["source"][:50]
        page = r.get("page")
        text = r["text"]
        if total + len(text) > max_chars:
            text = text[:max_chars - total]
        citation = f"[{src}, page {page}]" if page is not None else f"[Source: {src}]"
        parts.append(f"{citation}\n{text}")
        total += len(text)
        if total >= max_chars:
            break
    return "\n\n---\n\n".join(parts)


def build_book_context(kb, question: str, topics: list[str], bundle: Optional[dict],
                        division: str = "D1", top_k: int = 4, max_chars: int = 2200) -> dict:
    """Returns {"query": str, "passages": [{"source","page"}...], "context": str}.
    `context` is empty if the knowledge base found nothing relevant — callers
    must not fabricate a fallback passage when this is empty. Retrieval runs
    exactly once (kb.search) and both `passages` and `context` are derived
    from that single result set, so the citations always match the text."""
    query = build_query(question, topics, bundle, division)
    if kb is None:
        return {"query": query, "passages": [], "context": ""}
    results = kb.search(query, top_k=top_k)
    passages = [{"source": r["source"], "page": r.get("page")} for r in results]
    context = _format_passages(results, max_chars=max_chars)
    return {"query": query, "passages": passages, "context": context}
