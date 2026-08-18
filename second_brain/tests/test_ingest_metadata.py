"""Offline regression test for Milestone 2 Step 3: file-level author/title
metadata in ingest().

    python3 second_brain/tests/test_ingest_metadata.py

Dry-runs ingest() against the real pilot corpus source dir into a SCRATCH
output path — never memory/corpora/*/chunks.json, the live index every
query actually reads (only fts.db is queried at request time; chunks.json
is the offline source of truth, rebuilt into fts.db by a separate step this
test never touches). Safe to run repeatedly with zero production risk.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from second_brain.ingest import _file_metadata, ingest

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


PILOT_SRC = Path("~/Desktop/AI Research Papers").expanduser()

if not PILOT_SRC.exists():
    print(f"SKIP: pilot source dir not found at {PILOT_SRC} — nothing to verify against")
    sys.exit(0)

print(f"[dry-run ingest of the pilot corpus into a scratch path: {PILOT_SRC}]")
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "chunks.json"
    result = ingest(str(PILOT_SRC), exts=(".md", ".txt", ".pdf", ".epub"), index_path=out)
    check("ingest completed without error", "error" not in result, str(result))
    check("scratch output written, not the live index",
          out.exists() and "memory/corpora" not in str(out), str(out))

    data = json.loads(out.read_text())
    chunks = data["chunks"]
    check("chunks produced", len(chunks) > 0, f"{len(chunks)} chunks")

    check("every chunk carries author and title keys (even if null)",
          all("author" in c and "title" in c for c in chunks))

    with_author = [c for c in chunks if c.get("author")]
    with_title = [c for c in chunks if c.get("title")]
    print(f"    {len(with_author)}/{len(chunks)} chunks have a non-null author, "
          f"{len(with_title)}/{len(chunks)} have a non-null title")
    check("at least some real PDFs in this corpus carry title metadata",
          len(with_title) > 0,
          "if this ever fails, re-check with a corpus known to have PDF metadata "
          "before assuming a code regression — not every PDF embeds it")

    # Same file's chunks must agree — metadata is per-file, not per-chunk.
    by_source: dict[str, list[dict]] = {}
    for c in chunks:
        by_source.setdefault(c["source"], []).append(c)
    disagreements = [src for src, cs in by_source.items()
                     if len({c.get("author") for c in cs}) > 1
                     or len({c.get("title") for c in cs}) > 1]
    check("all chunks from the same file agree on author/title",
          not disagreements, str(disagreements[:3]))

print("\n[never fabricates — a file with no embedded metadata gets None, not a guess]")
import tempfile as _tf
with _tf.TemporaryDirectory() as tmp:
    blank = Path(tmp) / "no_metadata.txt"
    blank.write_text("plain text file with no embedded metadata whatsoever")
    meta = _file_metadata(blank)
    check("unsupported extension (.txt) returns None for both fields",
          meta == {"author": None, "title": None}, str(meta))

print("\n[a file that fails to parse at all still returns nullable metadata, not a crash]")
with _tf.TemporaryDirectory() as tmp:
    broken = Path(tmp) / "broken.pdf"
    broken.write_bytes(b"not actually a pdf")
    meta = _file_metadata(broken)
    check("malformed PDF doesn't raise, returns nulls",
          meta == {"author": None, "title": None}, str(meta))

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
