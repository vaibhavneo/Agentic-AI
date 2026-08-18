"""Offline regression test for Milestone 2 Step 7: fts.py's widened schema
(author/title/chapter/page_start/page_end).

    python3 second_brain/tests/test_fts_schema.py

Builds a real (throwaway) FTS5 db from synthetic chunks.json content in a
scratch directory — never a real corpus. Confirms the new columns round-trip
through build()+search(), that a corpus with NO metadata at all (the state
every un-migrated shelf is in until it's re-ingested) still builds and
searches cleanly with NULLs, and that build() is idempotent (rebuilding
doesn't accumulate stale rows).
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from second_brain import fts

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


def write_chunks(path: Path, records: list[dict]):
    path.write_text(json.dumps({"chunks": records}, ensure_ascii=False))


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    fts.CORPORA_DIR = tmp                     # redirect away from real corpora entirely

    print("[a corpus WITH full metadata builds and searches correctly]")
    src = tmp / "with-meta" / "chunks.json"
    src.parent.mkdir(parents=True)
    write_chunks(src, [
        {"text": "Backpropagation computes gradients via the chain rule through a network.",
         "source": "book.pdf", "chunk_id": 0, "author": "Ian Goodfellow", "title": "Deep Learning",
         "chapter": "Chapter 6", "page_start": 200, "page_end": 201},
        {"text": "A completely unrelated sentence about gardening and soil composition.",
         "source": "book.pdf", "chunk_id": 1, "author": "Ian Goodfellow", "title": "Deep Learning",
         "chapter": "Chapter 6", "page_start": 202, "page_end": 202},
    ])
    result = fts.build("with-meta", chunks_path=src)
    check("build succeeds", "error" not in result, str(result))
    hits = fts.search("with-meta", "backpropagation gradients chain rule")
    check("search returns a hit", len(hits) > 0)
    if hits:
        h = hits[0]
        check("author round-trips", h.get("author") == "Ian Goodfellow", str(h))
        check("title round-trips", h.get("title") == "Deep Learning", str(h))
        check("chapter round-trips", h.get("chapter") == "Chapter 6", str(h))
        check("page_start round-trips", h.get("page_start") == 200, str(h))
        check("page_end round-trips", h.get("page_end") == 201, str(h))

    print("\n[a corpus with NO metadata at all — the pre-Milestone-2 state — builds and searches with NULLs, not a crash]")
    src2 = tmp / "no-meta" / "chunks.json"
    src2.parent.mkdir(parents=True)
    write_chunks(src2, [
        {"text": "Reinforcement learning trains an agent via reward signals over time.",
         "source": "old_book.pdf", "chunk_id": 0},   # no author/title/chapter/page keys at all
    ])
    result2 = fts.build("no-meta", chunks_path=src2)
    check("build succeeds on an old-schema corpus", "error" not in result2, str(result2))
    hits2 = fts.search("no-meta", "reinforcement learning reward agent")
    check("search returns a hit for the un-migrated corpus", len(hits2) > 0)
    if hits2:
        h2 = hits2[0]
        check("author is None, not a crash or a fabricated value", h2.get("author") is None, str(h2))
        check("title is None", h2.get("title") is None, str(h2))
        check("chapter is None", h2.get("chapter") is None, str(h2))
        check("page_start is None", h2.get("page_start") is None, str(h2))
        check("all the original fields (text/source/raw_score) are still present",
              "text" in h2 and "source" in h2 and "raw_score" in h2, str(h2))

    print("\n[build() is idempotent — rebuilding doesn't accumulate stale rows]")
    fts.build("with-meta", chunks_path=src)
    fts.build("with-meta", chunks_path=src)
    hits3 = fts.search("with-meta", "backpropagation gradients chain rule")
    check("still exactly one match after rebuilding twice, not duplicated",
          len(hits3) == 1, f"{len(hits3)} hits")

    print("\n[status() reports has_index correctly for both corpora]")
    rows = {r["corpus"]: r for r in fts.status()}
    check("with-meta has an index", rows.get("with-meta", {}).get("has_index") is True)
    check("no-meta has an index", rows.get("no-meta", {}).get("has_index") is True)

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
