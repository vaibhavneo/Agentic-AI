"""
Second Brain MVP — Ingest (Phase 1)
Walks a source dir (md/txt; pdf via pypdf), chunks ~1200 chars on paragraph
boundaries, writes memory/index/chunks.json. Reuses the proven pattern from
vedic_astro/knowledge/ingest.py (chunk + JSON cache), minus book-specific code.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CHUNK_SIZE = 1200
INDEX_PATH = Path(__file__).parent.parent / "memory" / "index" / "chunks.json"


def _read_text(path: Path) -> str:
    if path.suffix.lower() in (".md", ".txt"):
        return path.read_text(errors="ignore")
    if path.suffix.lower() == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return "\n".join(pg.extract_text() or "" for pg in reader.pages)
        except Exception:
            return ""
    return ""


def _chunk(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split on paragraph boundaries, packing to ~size chars."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 > size and buf:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def ingest(source_dir: str, exts: tuple[str, ...] = (".md", ".txt"),
           index_path: str | Path | None = None,
           chunk_size: int = CHUNK_SIZE) -> dict:
    """Ingest all matching files under source_dir into a chunk index.

    index_path: where to write the index. Defaults to the legacy single-index
    location for backward compatibility; the Corpus Manager passes a
    per-corpus path (v1.1 — the change that retires the one-index world).
    """
    src = Path(source_dir).expanduser()
    if not src.exists():
        return {"error": f"source not found: {src}"}
    out_path = Path(index_path).expanduser() if index_path else INDEX_PATH

    records = []
    files = sorted(f for f in src.rglob("*") if f.suffix.lower() in exts)
    for f in files:
        text = _read_text(f)
        if not text.strip():
            continue
        for i, chunk in enumerate(_chunk(text, size=chunk_size)):
            records.append({
                "source": str(f.relative_to(src)),
                "chunk_id": i,
                "text": chunk,
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"source_dir": str(src), "n_files": len(files), "chunks": records},
        ensure_ascii=False))
    return {"files": len(files), "chunks": len(records), "index": str(out_path)}


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else \
        "~/Documents/brain/Vaibhav's Second Brain/wiki/books"
    print(json.dumps(ingest(src), indent=2))
