"""
Astrology Book Knowledge Ingestor
====================================
Reads PDF books from the Astrology Books folder using pypdf.
Chunks text, indexes it, and saves a searchable knowledge base.
Uses TF-IDF retrieval (no external vector DB needed).
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

try:
    import pypdf
    PYPDF_OK = True
except ImportError:
    PYPDF_OK = False


BOOKS_DIR = Path("/Users/vaibhavgupta/Desktop/Astrology Books")
KB_PATH   = Path(__file__).parent.parent / "data" / "knowledge_base" / "knowledge_base.json"

CHUNK_SIZE    = 600   # chars per chunk
CHUNK_OVERLAP = 100   # overlap between chunks


# ── Text cleaning ──────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\x20-\x7E\n]", " ", text)
    text = re.sub(r"\.{3,}", "...", text)
    return text.strip()


# ── Chunking ───────────────────────────────────────────────────────────────

def _chunk(text: str, source: str, page: int) -> list[dict]:
    chunks = []
    start  = 0
    while start < len(text):
        end   = start + CHUNK_SIZE
        chunk = text[start:end]
        if len(chunk) > 80:  # skip tiny fragments
            chunks.append({
                "text":   chunk,
                "source": source,
                "page":   page,
            })
        start = end - CHUNK_OVERLAP
    return chunks


# ── PDF reading ────────────────────────────────────────────────────────────

def read_pdf_book(path: Path, max_pages: int = 150) -> list[dict]:
    """Extract text chunks from a PDF book."""
    if not PYPDF_OK:
        return []
    chunks = []
    try:
        reader = pypdf.PdfReader(str(path))
        total  = min(len(reader.pages), max_pages)
        source = path.stem[:80]
        for i in range(total):
            try:
                page_text = reader.pages[i].extract_text() or ""
                page_text = _clean(page_text)
                if len(page_text) > 100:
                    chunks.extend(_chunk(page_text, source, i + 1))
            except Exception:
                continue
    except Exception as e:
        print(f"    [warn] {path.name[:50]}: {e}")
    return chunks


# ── TF-IDF index ───────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())


def build_tfidf_index(chunks: list[dict]) -> dict:
    """Build TF-IDF index over all chunks."""
    doc_tokens = [_tokenize(c["text"]) for c in chunks]
    N   = len(doc_tokens)
    df: dict[str, int] = defaultdict(int)
    for tokens in doc_tokens:
        for t in set(tokens):
            df[t] += 1
    idf = {t: math.log((N + 1) / (cnt + 1)) + 1.0 for t, cnt in df.items()}
    return {"idf": idf}


def tfidf_search(query: str, chunks: list[dict], idf: dict[str, float],
                 top_k: int = 6) -> list[dict]:
    """Retrieve most relevant chunks for a query."""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    scored = []
    for chunk in chunks:
        doc_tokens = _tokenize(chunk["text"])
        freq: dict[str, int] = defaultdict(int)
        for t in doc_tokens:
            freq[t] += 1
        total = len(doc_tokens) or 1
        score = sum(
            (freq[t] / total) * idf.get(t, 0.0)
            for t in q_tokens if t in freq
        )
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    # deduplicate by source proximity
    seen_sources: dict[str, int] = {}
    results = []
    for score, chunk in scored:
        src = chunk["source"]
        if seen_sources.get(src, 0) < 2:  # max 2 chunks per book
            results.append(chunk)
            seen_sources[src] = seen_sources.get(src, 0) + 1
        if len(results) >= top_k:
            break
    return results


# ── Main ingestor ──────────────────────────────────────────────────────────

class KnowledgeBase:
    """
    Loaded knowledge base with search capability.
    Loads from disk; ingests books if not already done.
    """

    def __init__(self):
        self.chunks: list[dict] = []
        self.idf: dict[str, float] = {}
        self.loaded = False

    def load_or_build(self, force_rebuild: bool = False) -> None:
        KB_PATH.parent.mkdir(parents=True, exist_ok=True)

        if KB_PATH.exists() and not force_rebuild:
            print("📚 Loading knowledge base from cache...")
            data = json.loads(KB_PATH.read_text())
            self.chunks = data["chunks"]
            self.idf    = data["idf"]
            self.loaded = True
            print(f"   Loaded {len(self.chunks):,} chunks from {data.get('num_books', '?')} books")
            return

        print("📖 Ingesting astrology books (first-time setup, ~2 min)...")
        all_chunks: list[dict] = []
        pdf_files = sorted(BOOKS_DIR.glob("*.pdf"))
        total = len(pdf_files)

        for idx, pdf_path in enumerate(pdf_files, 1):
            print(f"   [{idx}/{total}] {pdf_path.name[:70]}")
            chunks = read_pdf_book(pdf_path, max_pages=120)
            all_chunks.extend(chunks)
            print(f"          → {len(chunks)} chunks")

        print(f"\n   Building search index over {len(all_chunks):,} chunks...")
        idx_data = build_tfidf_index(all_chunks)

        save_data = {
            "chunks":    all_chunks,
            "idf":       idx_data["idf"],
            "num_books": total,
            "built_at":  time.strftime("%Y-%m-%d %H:%M"),
        }
        KB_PATH.write_text(json.dumps(save_data, indent=2))
        self.chunks = all_chunks
        self.idf    = idx_data["idf"]
        self.loaded = True
        print(f"✅ Knowledge base built: {len(all_chunks):,} chunks, {total} books")

    def search(self, query: str, top_k: int = 6) -> list[dict]:
        if not self.loaded:
            return []
        return tfidf_search(query, self.chunks, self.idf, top_k)

    def format_context(self, query: str, top_k: int = 5, max_chars: int = 3000) -> str:
        """Formats retrieved chunks with an explicit (Title, page N) citation
        per passage — the page number is real (extracted per-PDF-page at
        ingest time), so a caller instructing the LLM to cite 'exactly as
        shown' never has to let it invent one."""
        results = self.search(query, top_k)
        if not results:
            return ""
        parts = []
        total = 0
        for r in results:
            src  = r["source"][:50]
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


# Singleton
_kb_instance: Optional[KnowledgeBase] = None

def get_knowledge_base() -> KnowledgeBase:
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
        _kb_instance.load_or_build()
    return _kb_instance
