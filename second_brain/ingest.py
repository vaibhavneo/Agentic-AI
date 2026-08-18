"""
Second Brain MVP — Ingest (Phase 1)
Walks a source dir (md/txt; pdf via pypdf), chunks ~1200 chars on paragraph
boundaries, writes memory/index/chunks.json. Reuses the proven pattern from
vedic_astro/knowledge/ingest.py (chunk + JSON cache), minus book-specific code.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CHUNK_SIZE = 1200
MIN_CHUNK_SIZE = 400   # below this a chunk carries too little context to rank on
INDEX_PATH = Path(__file__).parent.parent / "memory" / "index" / "chunks.json"


def _sanitize(text: str) -> str:
    """Strip lone UTF-16 surrogates that pypdf occasionally emits when a PDF's
    font encoding is malformed (seen on styled math glyphs in finance/quant
    textbooks). A lone surrogate can't round-trip through utf-8, so leaving it
    in crashes the index write later (json.dumps -> write_text) — better to
    drop it here, once, for every source, than let one bad file blank the
    whole corpus."""
    return text.encode("utf-8", "surrogatepass").decode("utf-8", "ignore")


def _read_epub(path: Path) -> str:
    """Extract readable text from an EPUB (a zip of XHTML documents). Uses
    ebooklib to walk the spine and a minimal tag-stripper to turn each XHTML
    chapter into plain text — no extra HTML-parser dependency, and robust to
    the messy markup real e-books ship with."""
    import ebooklib
    from ebooklib import epub
    book = epub.read_epub(str(path))
    parts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", "ignore")
        html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)  # drop scripts/styles
        text = re.sub(r"(?s)<[^>]+>", " ", html)                        # strip remaining tags
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text).replace("&lt;", "<").replace("&gt;", ">")
        parts.append(text)
    return _sanitize(re.sub(r"[ \t]+\n", "\n", "\n\n".join(parts)))


def _read_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".md", ".txt"):
        return path.read_text(errors="ignore")
    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return _sanitize("\n".join(pg.extract_text() or "" for pg in reader.pages))
        except Exception:
            return ""
    if ext == ".epub":
        try:
            return _read_epub(path)
        except Exception:
            return ""
    return ""


def _file_metadata(path: Path) -> dict:
    """Author/title straight from the file's own embedded metadata — never a
    guess. Any field the format doesn't carry, or that fails to parse, comes
    back None rather than a fabricated value, matching the same anti-
    fabrication principle the AI Brain honesty-badge fix already applies to
    citations: a chunk should claim only what it actually knows.

    Re-parses the file (pypdf.PdfReader / epub.read_epub) separately from
    _read_text()'s own parse of the same file — a real but small cost,
    acceptable for an offline ingest job; step 4 folds page-boundary
    extraction into the same walk and can absorb this into one parse then.
    """
    ext = path.suffix.lower()
    author = title = None
    try:
        if ext == ".pdf":
            import pypdf
            meta = pypdf.PdfReader(str(path)).metadata
            if meta:
                author = (meta.author or "").strip() or None
                title = (meta.title or "").strip() or None
        elif ext == ".epub":
            from ebooklib import epub
            book = epub.read_epub(str(path))
            creators = book.get_metadata("DC", "creator")
            titles = book.get_metadata("DC", "title")
            if creators and creators[0][0]:
                author = creators[0][0].strip() or None
            if titles and titles[0][0]:
                title = titles[0][0].strip() or None
    except Exception:
        pass
    return {"author": author, "title": title}


def _split_oversized(para: str, size: int) -> list[str]:
    """Break a paragraph that is already larger than `size` on sentence
    boundaries, hard-splitting any single sentence that still doesn't fit.

    Needed because PDF and epub extraction often yields no blank lines at
    all, so an entire chapter arrives as one 'paragraph'. The old packer
    emitted such a paragraph verbatim, producing chunks up to 73k chars.
    """
    if len(para) <= size:
        return [para]
    out, buf = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", para):
        if len(sent) > size:                      # single monster sentence
            if buf:
                out.append(buf)
                buf = ""
            out.extend(sent[k:k + size] for k in range(0, len(sent), size))
            continue
        if buf and len(buf) + len(sent) + 1 > size:
            out.append(buf)
            buf = sent
        else:
            buf = f"{buf} {sent}" if buf else sent
    if buf:
        out.append(buf)
    return out


def _chunk(text: str, size: int = CHUNK_SIZE,
           min_size: int = MIN_CHUNK_SIZE) -> list[str]:
    """Split into ~size-char chunks on paragraph boundaries.

    Two properties the naive packer lacked, both of which wrecked retrieval:
      * paragraphs longer than `size` are subdivided rather than emitted
        whole, so no chunk is vastly oversized;
      * runt chunks are merged forward, so a heading like "Quantum
        Mechanics" is indexed together with the prose it introduces instead
        of becoming a standalone hit that carries no information.
    """
    units: list[str] = []
    for p in (p.strip() for p in text.split("\n\n")):
        if p:
            units.extend(_split_oversized(p, size))

    chunks: list[str] = []
    buf = ""
    for u in units:
        if buf and len(buf) + len(u) + 2 > size:
            chunks.append(buf)
            buf = u
        else:
            buf = f"{buf}\n\n{u}" if buf else u
    if buf:
        chunks.append(buf)

    # Fold anything still too short into its neighbour (a trailing heading, or
    # a short run between two oversized paragraphs). Cap the merge so this
    # can't rebuild an enormous chunk.
    merged: list[str] = []
    for c in chunks:
        if merged and (len(c) < min_size or len(merged[-1]) < min_size) \
                and len(merged[-1]) + len(c) + 2 <= int(size * 1.5):
            merged[-1] = f"{merged[-1]}\n\n{c}"
        else:
            merged.append(c)
    return merged


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
        meta = _file_metadata(f)
        for i, chunk in enumerate(_chunk(text, size=chunk_size)):
            records.append({
                "source": str(f.relative_to(src)),
                "chunk_id": i,
                "text": chunk,
                "author": meta["author"],
                "title": meta["title"],
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
