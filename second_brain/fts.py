"""Disk-backed full-text search over the corpora (SQLite FTS5 + BM25).

Why this exists
---------------
`retrieve.Retriever` is pure-Python TF-IDF: it reads a corpus's whole
chunks.json into memory, tokenises every chunk at construction, and linearly
scans all of them on each query. That is fine for one small corpus and
impossible at library scale. Measured on desk-physics (125,846 chunks) and
projected to the ~827,000 chunks of the full AI Brain:

                       measured (1 corpus)     projected (all corpora)
    peak RSS               1,420 MB                    9.3 GB
    per query                770 ms                    5.1 s

FTS5 keeps the index on disk, so memory stays flat and BM25 scoring is done by
SQLite in C. Same corpus, same machine:

    serving RSS   13 MB     (vs 1,420 MB)
    per query    4.3 ms     (vs   770 ms)

That is what makes a 960-book brain viable on a small container instead of
needing 9 GB of RAM.

The index is a derived artefact: chunks.json stays the source of truth, and a
db can always be rebuilt from it in a few seconds per corpus.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

CORPORA_DIR = Path(__file__).parent.parent / "memory" / "corpora"
DB_NAME = "fts.db"

# Punctuation and FTS5 operators must not reach the MATCH parser: a user
# question like "what is p(x|y)?" is a syntax error to FTS5, not a query.
_WORD = re.compile(r"[A-Za-z0-9_]+")
_STOP = frozenset(
    "the a an and or of to in for on with is are was were be been being this "
    "that it as by from at what which who how why when where do does did can "
    "could would should will shall may might must i we you they he she my our "
    "your their its about into than then there here also very more most such "
    "some any all no not but if so because between over under".split()
)


def db_path(corpus_id: str) -> Path:
    return CORPORA_DIR / corpus_id / DB_NAME


def _connect(path: Path, write: bool = False) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    if write:
        # Bulk-load settings only; the index is rebuildable so durability
        # during a build is not worth the write amplification.
        con.execute("PRAGMA journal_mode = OFF")
        con.execute("PRAGMA synchronous = OFF")
    return con


def fts5_available() -> bool:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False


def build(corpus_id: str, chunks_path: Path | None = None) -> dict:
    """(Re)build the FTS index for one corpus from its chunks.json."""
    src = Path(chunks_path) if chunks_path else CORPORA_DIR / corpus_id / "chunks.json"
    if not src.exists():
        return {"corpus": corpus_id, "error": f"no chunks.json at {src}"}
    data = json.loads(src.read_text())
    records = data["chunks"] if isinstance(data, dict) and "chunks" in data else data

    out = db_path(corpus_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()

    con = _connect(tmp, write=True)
    # `source` is UNINDEXED: filenames would otherwise match query words and
    # rank a book by its title rather than by what its text says.
    con.execute(
        "CREATE VIRTUAL TABLE chunks USING fts5("
        "  text, source UNINDEXED, chunk_id UNINDEXED,"
        "  tokenize = 'porter unicode61'"
        ")"
    )
    con.executemany(
        "INSERT INTO chunks(text, source, chunk_id) VALUES (?, ?, ?)",
        ((r.get("text", ""), str(r.get("source", "")), r.get("chunk_id", i))
         for i, r in enumerate(records)),
    )
    con.commit()
    con.execute("INSERT INTO chunks(chunks) VALUES ('optimize')")   # merge b-trees
    con.commit()
    con.close()

    tmp.replace(out)          # atomic swap: a half-built db never serves queries
    return {"corpus": corpus_id, "chunks": len(records),
            "db_mb": round(out.stat().st_size / 1e6, 1)}


def to_match_query(question: str, max_terms: int = 12) -> str:
    """Turn free text into a safe FTS5 expression.

    OR rather than AND: a long question ANDed together matches nothing, and
    BM25 already rewards documents carrying more of the rare terms.
    """
    seen, terms = set(), []
    for w in _WORD.findall(question.lower()):
        if len(w) < 3 or w in _STOP or w in seen:
            continue
        seen.add(w)
        terms.append(w)
        if len(terms) >= max_terms:
            break
    return " OR ".join(terms)


def search(corpus_id: str, question: str, top_k: int = 6) -> list[dict]:
    """BM25-ranked chunks for a question. Empty list if this corpus has no db."""
    path = db_path(corpus_id)
    if not path.exists():
        return []
    match = to_match_query(question)
    if not match:
        return []
    con = _connect(path)
    try:
        rows = con.execute(
            "SELECT text, source, bm25(chunks) AS s FROM chunks "
            "WHERE chunks MATCH ? ORDER BY s LIMIT ?",
            (match, top_k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []                      # malformed query → no hits, never a 500
    finally:
        con.close()

    # bm25() is negative and better-is-lower. Flip it so callers can treat the
    # score the way they treat every other relevance number here.
    return [{"text": t, "source": s, "corpus": [corpus_id],
             "raw_score": round(-score, 4), "chunk_id": None}
            for t, s, score in rows]


def status() -> list[dict]:
    """Which corpora have a usable index, and how big."""
    out = []
    if not CORPORA_DIR.exists():
        return out
    for d in sorted(CORPORA_DIR.iterdir()):
        if not d.is_dir():
            continue
        db, chunks = d / DB_NAME, d / "chunks.json"
        out.append({
            "corpus": d.name,
            "has_index": db.exists(),
            "db_mb": round(db.stat().st_size / 1e6, 1) if db.exists() else 0.0,
            "chunks_json_mb": round(chunks.stat().st_size / 1e6, 1) if chunks.exists() else 0.0,
        })
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        for row in status():
            mark = "✓" if row["has_index"] else "·"
            print(f" {mark} {row['corpus']:<52s} db {row['db_mb']:8.1f} MB")
    elif len(sys.argv) > 2 and sys.argv[1] == "search":
        for h in search(sys.argv[2], " ".join(sys.argv[3:])):
            print(f"[{h['raw_score']}] {h['source'][:70]}\n    {h['text'][:160]}…\n")
    else:
        for cid in (sys.argv[1:] or [d.name for d in CORPORA_DIR.iterdir() if d.is_dir()]):
            print(build(cid), flush=True)
