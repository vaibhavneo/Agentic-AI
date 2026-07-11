from __future__ import annotations
"""
Scalable incremental knowledge base ingestion.

Key design:
  - Hash-based tracking: only re-ingests new/changed files
  - Chunked TF-IDF index stored as pickle
  - Metadata per chunk: source, category, page, file hash
  - Add new books by adding to sources.py and running --update
"""
import hashlib
import json
import math
import pickle
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import pypdf

BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "data"
INDEX_PATH = DATA_DIR / "index" / "knowledge_base.pkl"
META_PATH  = DATA_DIR / "index" / "ingested_files.json"

CHUNK_WORDS  = 500
CHUNK_OVERLAP = 80


# ── Text utilities ─────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\x20-\x7E]", " ", text)
    return text.strip()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z]{2,}", text.lower())


def _chunk_text(text: str, source: str, category: str, file_hash: str) -> list[dict]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + CHUNK_WORDS])
        if len(chunk) > 100:
            chunks.append({
                "text": chunk,
                "source": source,
                "category": category,
                "file_hash": file_hash,
            })
        i += CHUNK_WORDS - CHUNK_OVERLAP
    return chunks


def _file_hash(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.stat().st_mtime_ns.to_bytes(8, "big"))
    h.update(str(path).encode())
    return h.hexdigest()


def _read_pdf(path: Path, max_pages: int) -> str:
    try:
        reader = pypdf.PdfReader(str(path))
        parts = []
        for page in reader.pages[:max_pages]:
            t = page.extract_text() or ""
            if len(t.strip()) > 50:
                parts.append(_clean(t))
        return "\n".join(parts)
    except Exception as e:
        print(f"  SKIP {path.name[:60]}: {e}")
        return ""


# ── TF-IDF index ──────────────────────────────────────────────────────────

def _build_tfidf(chunks: list[dict]) -> tuple[list[Counter], dict[str, float]]:
    tfs = []
    df: Counter = Counter()
    for chunk in chunks:
        tokens = _tokenize(chunk["text"])
        tf = Counter(tokens)
        tfs.append(tf)
        df.update(set(tokens))
    N = max(len(chunks), 1)
    idf = {t: math.log((N + 1) / (c + 1)) + 1 for t, c in df.items()}
    return tfs, idf


def _score(query_tokens: list[str], tf: Counter, idf: dict) -> float:
    q_vec = {t: idf.get(t, 0) for t in query_tokens}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
    score = sum(tf.get(t, 0) * w for t, w in q_vec.items())
    doc_norm = math.sqrt(sum((tf.get(t, 0) * idf.get(t, 0)) ** 2 for t in q_vec)) or 1.0
    return score / (q_norm * doc_norm)


# ── Public API ────────────────────────────────────────────────────────────

def load_index() -> Optional[dict]:
    if INDEX_PATH.exists():
        with open(INDEX_PATH, "rb") as f:
            return pickle.load(f)
    return None


def _load_meta() -> dict:
    if META_PATH.exists():
        return json.loads(META_PATH.read_text())
    return {"ingested": {}}


def _save_meta(meta: dict) -> None:
    META_PATH.write_text(json.dumps(meta, indent=2))


def _save_index(kb: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "index").mkdir(exist_ok=True)
    with open(INDEX_PATH, "wb") as f:
        pickle.dump(kb, f)


def ingest(force: bool = False, verbose: bool = True) -> dict:
    """
    Ingest all source books into the knowledge base.
    Incremental: only processes new/changed files unless force=True.
    """
    from knowledge.sources import BOOK_SOURCES

    existing_kb = load_index() if not force else None
    meta = _load_meta() if not force else {"ingested": {}}

    existing_chunks: list[dict] = existing_kb["chunks"] if existing_kb else []
    existing_tfs: list[Counter] = existing_kb["tfs"] if existing_kb else []

    # Remove chunks from files that no longer exist
    valid_hashes = set()
    new_chunks: list[dict] = []
    new_tfs: list[Counter] = []

    # Collect all PDFs to process
    to_process: list[tuple[Path, str, int]] = []  # (path, category, max_pages)
    for src in BOOK_SOURCES:
        p = src["path"]
        if not p.exists():
            continue
        cat = src["category"]
        max_pg = src["max_pages"]
        pattern = "**/*.pdf" if src.get("recurse") else "*.pdf"
        for pdf in sorted(p.glob(pattern)):
            to_process.append((pdf, cat, max_pg))
        # EPUBs: skip for now (no epub parser installed)

    if verbose:
        print(f"Found {len(to_process)} PDFs across {len(BOOK_SOURCES)} source directories")

    new_file_count = 0
    for pdf, category, max_pages in to_process:
        fhash = _file_hash(pdf)
        valid_hashes.add(fhash)

        if not force and fhash in meta["ingested"]:
            # Already ingested — keep existing chunks
            for i, ch in enumerate(existing_chunks):
                if ch.get("file_hash") == fhash:
                    new_chunks.append(ch)
                    new_tfs.append(existing_tfs[i] if i < len(existing_tfs) else Counter(_tokenize(ch["text"])))
            continue

        # New or changed file
        new_file_count += 1
        if verbose:
            print(f"  [{category}] {pdf.name[:65]}...")
        text = _read_pdf(pdf, max_pages)
        if not text:
            continue

        file_chunks = _chunk_text(text, pdf.name, category, fhash)
        for ch in file_chunks:
            new_chunks.append(ch)
            new_tfs.append(Counter(_tokenize(ch["text"])))
        meta["ingested"][fhash] = {"name": pdf.name, "category": category, "chunks": len(file_chunks)}

    if verbose:
        print(f"\nProcessed {new_file_count} new files, {len(new_chunks):,} total chunks")
        if new_file_count > 0:
            print("Rebuilding TF-IDF index...")

    # Rebuild IDF over all chunks
    _, idf = _build_tfidf(new_chunks)

    # Category stats
    cat_counts: Counter = Counter(ch["category"] for ch in new_chunks)
    book_counts: Counter = Counter(ch["source"] for ch in new_chunks)

    kb = {
        "chunks": new_chunks,
        "tfs": new_tfs,
        "idf": idf,
        "total": len(new_chunks),
        "total_books": len(book_counts),
        "categories": dict(cat_counts),
    }
    _save_index(kb)
    _save_meta(meta)

    if verbose:
        print(f"Knowledge base: {len(new_chunks):,} chunks from {len(book_counts)} books")
        for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {cnt:,} chunks")

    return kb


def search(kb: dict, query: str, top_k: int = 6, category: str = None) -> list[dict]:
    """Search the knowledge base. Optionally filter by category."""
    query_tokens = _tokenize(query)
    idf = kb["idf"]
    tfs = kb["tfs"]
    chunks = kb["chunks"]

    scores = []
    for i, tf in enumerate(tfs):
        ch = chunks[i]
        if category and ch.get("category") != category:
            scores.append(-1)
            continue
        scores.append(_score(query_tokens, tf, idf))

    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k * 2]
    results = []
    seen_sources = set()
    for i in top:
        if scores[i] <= 0:
            continue
        ch = chunks[i]
        # Diversity: max 2 chunks per source
        src = ch["source"]
        if seen_sources.count(src) if hasattr(seen_sources, 'count') else list(seen_sources).count(src) >= 2:
            continue
        results.append({
            "text": ch["text"],
            "source": ch["source"],
            "category": ch["category"],
            "score": round(scores[i], 4),
        })
        seen_sources.add(src)
        if len(results) >= top_k:
            break
    return results


if __name__ == "__main__":
    force = "--force" in sys.argv
    quiet = "--quiet" in sys.argv
    ingest(force=force, verbose=not quiet)
