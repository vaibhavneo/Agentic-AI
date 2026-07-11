from __future__ import annotations
"""
Ingest physics books into a TF-IDF knowledge base.
Prioritises: Feynman Lectures, Griffiths, Shankar, Susskind, Zettili, Sakurai.
Run: python3 -m knowledge.ingest
"""
import json
import math
import pickle
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pypdf

PHYSICS_DIR = Path("/Users/vaibhavgupta/Desktop/Physics")
DATA_DIR    = Path(__file__).parent.parent / "data"
KB_PATH     = DATA_DIR / "knowledge_base.pkl"

# Books to prioritise (read more pages from these)
TIER1 = [
    "Feynman Lectures",
    "Introduction to Quantum Mechanics",   # Griffiths
    "Principles of Quantum Mechanics",     # Shankar
    "Quantum Mechanics The Theoretical Minimum",  # Susskind
    "Modern Quantum Mechanics",            # Sakurai
    "Quantum Mechanics Concepts and Applications",  # Zettili
    "Mastering Quantum Mechanics",         # Zwiebach
    "Fundamentals of Quantum Mechanics",
    "A Students Guide to the Schrödinger",
]

CHUNK_SIZE  = 600    # ~150 words per chunk
CHUNK_OVER  = 100    # overlap
MAX_PAGES_TIER1 = 300
MAX_PAGES_OTHER = 80


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\x20-\x7E\n]", " ", text)
    return text.strip()


def _is_tier1(path: Path) -> bool:
    name = path.name
    return any(t.lower() in name.lower() for t in TIER1)


def _read_pdf(path: Path, max_pages: int) -> list[str]:
    try:
        reader = pypdf.PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages[:max_pages]):
            text = page.extract_text() or ""
            if len(text.strip()) > 50:
                pages.append(_clean(text))
        return pages
    except Exception as e:
        print(f"  SKIP {path.name}: {e}")
        return []


def _chunk(text: str) -> list[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + CHUNK_SIZE])
        if len(chunk) > 80:
            chunks.append(chunk)
        i += CHUNK_SIZE - CHUNK_OVER
    return chunks


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z]{2,}", text.lower())


def build_tfidf(chunks: list[str]) -> tuple[list[Counter], dict[str, float]]:
    tfs = []
    df: Counter = Counter()
    for chunk in chunks:
        tokens = _tokenize(chunk)
        tf = Counter(tokens)
        tfs.append(tf)
        df.update(set(tokens))
    N = len(chunks)
    idf = {term: math.log((N + 1) / (cnt + 1)) + 1 for term, cnt in df.items()}
    return tfs, idf


def ingest(force: bool = False) -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if KB_PATH.exists() and not force:
        print(f"Knowledge base already exists ({KB_PATH}). Use --force to rebuild.")
        with open(KB_PATH, "rb") as f:
            return pickle.load(f)

    print("Scanning physics books...")
    pdfs = list(PHYSICS_DIR.rglob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs")

    all_chunks: list[str] = []
    sources: list[str] = []

    for pdf in sorted(pdfs):
        tier1 = _is_tier1(pdf)
        max_pages = MAX_PAGES_TIER1 if tier1 else MAX_PAGES_OTHER
        label = "[TIER1]" if tier1 else "      "
        print(f"  {label} {pdf.name[:70]}...")
        pages = _read_pdf(pdf, max_pages)
        for page_text in pages:
            for chunk in _chunk(page_text):
                all_chunks.append(chunk)
                sources.append(pdf.name)

    print(f"\nTotal chunks: {len(all_chunks):,}")
    print("Building TF-IDF index...")
    tfs, idf = build_tfidf(all_chunks)

    kb = {
        "chunks": all_chunks,
        "sources": sources,
        "tfs": tfs,
        "idf": idf,
        "total": len(all_chunks),
    }
    with open(KB_PATH, "wb") as f:
        pickle.dump(kb, f)
    print(f"Knowledge base saved → {KB_PATH}")
    return kb


def search(kb: dict, query: str, top_k: int = 6) -> list[dict]:
    query_tokens = _tokenize(query)
    idf = kb["idf"]
    tfs = kb["tfs"]
    chunks = kb["chunks"]
    sources = kb["sources"]

    # TF-IDF query vector
    q_vec = {t: idf.get(t, 0) for t in query_tokens}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0

    scores = []
    for i, tf in enumerate(tfs):
        score = sum(tf.get(t, 0) * w for t, w in q_vec.items())
        doc_norm = math.sqrt(sum((tf.get(t, 0) * idf.get(t, 0)) ** 2 for t in q_vec)) or 1.0
        scores.append(score / (q_norm * doc_norm))

    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [
        {"text": chunks[i], "source": sources[i], "score": round(scores[i], 4)}
        for i in top if scores[i] > 0
    ]


if __name__ == "__main__":
    force = "--force" in sys.argv
    ingest(force=force)
