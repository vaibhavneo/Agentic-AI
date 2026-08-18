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


def _flatten_toc(toc) -> dict[str, str]:
    """Map each real table-of-contents entry's spine filename (fragment
    stripped) to its title. book.toc is a nested structure of ebooklib Link
    objects and (Section, [children]) tuples — walk it recursively so an
    entry nested under a top-level "Part" heading is still found. When a
    file is referenced by more than one TOC entry (a chapter file plus its
    own sub-heading anchors, e.g. "1 Introduction" -> ch1.xhtml and
    "1.2 Related Work" -> ch1.xhtml#sec2), the FIRST entry for that file
    wins — TOC traversal order puts the chapter-level entry (no fragment)
    ahead of its own sub-section entries, so this reliably keeps the
    chapter title, not a sub-heading."""
    mapping: dict[str, str] = {}

    def walk(node):
        if isinstance(node, (list, tuple)):
            for n in node:
                walk(n)
        elif getattr(node, "href", None) and getattr(node, "title", None):
            href = node.href.split("#")[0]
            if href and href not in mapping:
                mapping[href] = node.title

    walk(toc)
    return mapping


def _chapter_for_offset(boundaries: list[tuple[int, str | None]], offset: int) -> str | None:
    """The chapter title whose spine item covers character `offset` in the
    joined EPUB text described by `boundaries` (see _read_epub_with_chapters)."""
    if not boundaries:
        return None
    chapter = boundaries[0][1]
    for b_offset, title in boundaries:
        if offset >= b_offset:
            chapter = title
        else:
            break
    return chapter


def _read_epub_with_chapters(path: Path) -> tuple[str, list[tuple[int, str | None]]]:
    """Same extraction as _read_epub() below — ebooklib spine walk, tag-
    strip, entity-decode, then the same final whitespace-collapse + sanitize
    pass on the whole joined string (preserved exactly, not applied per-item
    — _read_epub()'s trailing-whitespace regex behaves differently right at a
    part boundary depending on whether it runs before or after the join) —
    but also returns chapter_boundaries: (approximate char offset in the
    pre-final-pass joined string, chapter title or None) for each spine
    document, resolved from the book's own real table of contents, not a
    heuristic guess."""
    import ebooklib
    from ebooklib import epub
    book = epub.read_epub(str(path))
    toc_map = _flatten_toc(book.toc)

    parts: list[str] = []
    boundaries: list[tuple[int, str | None]] = []
    offset = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", "ignore")
        html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text).replace("&lt;", "<").replace("&gt;", ">")
        boundaries.append((offset, toc_map.get(item.get_name())))
        parts.append(text)
        offset += len(text) + 2            # +2 for the "\n\n" join separator below

    joined = _sanitize(re.sub(r"[ \t]+\n", "\n", "\n\n".join(parts)))
    return joined, boundaries


def _chunk_with_chapters(text: str, chapter_boundaries: list[tuple[int, str | None]],
                          size: int = CHUNK_SIZE, min_size: int = MIN_CHUNK_SIZE
                          ) -> list[tuple[str, dict]]:
    """Same packing algorithm as _chunk() (see _chunk_with_pages()'s
    docstring for why this is deliberately duplicated rather than shared).
    A chunk whose paragraphs span two different chapters — rare, since spine
    items are usually chapter-sized, but packing can still straddle a
    boundary right at the edge — gets chapter: None rather than guessing
    which one, matching the same anti-fabrication principle as the rest of
    this milestone: a chunk should claim only what it actually,
    unambiguously knows.

    Same sub-piece offset tracking as _chunk_with_pages() (see its docstring
    for the real bug this fixes): a paragraph can itself span a chapter
    boundary once _split_oversized() subdivides it, so the offset advances
    within a paragraph as its sub-pieces are consumed, not just between
    paragraphs."""
    raw_pieces = text.split("\n\n")
    units: list[tuple[str, str | None]] = []
    offset = 0
    for raw in raw_pieces:
        p = raw.strip()
        if p:
            sub_offset = 0
            for piece in _split_oversized(p, size):
                chapter = _chapter_for_offset(chapter_boundaries, offset + sub_offset)
                units.append((piece, chapter))
                sub_offset += len(piece) + 1
        offset += len(raw) + 2

    chunks: list[tuple[str, list]] = []
    buf, buf_chapters = "", []
    for u, chapter in units:
        if buf and len(buf) + len(u) + 2 > size:
            chunks.append((buf, buf_chapters))
            buf, buf_chapters = u, [chapter]
        else:
            buf = f"{buf}\n\n{u}" if buf else u
            buf_chapters.append(chapter)
    if buf:
        chunks.append((buf, buf_chapters))

    merged: list[tuple[str, list]] = []
    for c, chs in chunks:
        if merged and (len(c) < min_size or len(merged[-1][0]) < min_size) \
                and len(merged[-1][0]) + len(c) + 2 <= int(size * 1.5):
            merged[-1] = (f"{merged[-1][0]}\n\n{c}", merged[-1][1] + chs)
        else:
            merged.append((c, chs))

    out: list[tuple[str, dict]] = []
    for chunk_text, chs in merged:
        distinct = {c for c in chs if c is not None}
        meta = {"chapter": next(iter(distinct))} if len(distinct) == 1 else {}
        out.append((chunk_text, meta))
    return out


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


def _read_pdf_with_pages(path: Path) -> tuple[str, list[int]]:
    """Same extraction as _read_text()'s PDF branch — pypdf, pages joined with
    '\\n', then sanitized — but also returns page_boundaries, where
    boundaries[i] is the character offset in the returned text at which page
    i+1's content begins. Sanitizing per-page before joining (rather than
    sanitizing the whole joined string, as _read_text() does) keeps the
    boundary offsets exact even if a malformed page's surrogates get dropped;
    since _sanitize() only ever removes characters, never reorders or adds
    them, sanitizing each page then joining is equivalent to joining then
    sanitizing the whole for any well-formed neighbouring pages."""
    import pypdf
    reader = pypdf.PdfReader(str(path))
    page_texts = [_sanitize(pg.extract_text() or "") for pg in reader.pages]
    boundaries: list[int] = []
    offset = 0
    for t in page_texts:
        boundaries.append(offset)
        offset += len(t) + 1                      # +1 for the "\n" join() inserts
    return "\n".join(page_texts), boundaries


def _page_for_offset(boundaries: list[int], offset: int) -> int | None:
    """1-indexed page number containing character `offset` in the joined PDF
    text described by `boundaries` (see _read_pdf_with_pages)."""
    if not boundaries:
        return None
    page = 1
    for i, b in enumerate(boundaries):
        if offset >= b:
            page = i + 1
        else:
            break
    return page


def _chunk_with_pages(text: str, page_boundaries: list[int],
                       size: int = CHUNK_SIZE, min_size: int = MIN_CHUNK_SIZE
                       ) -> list[tuple[str, dict]]:
    """Same packing algorithm as _chunk() below — paragraph split, oversized-
    paragraph subdivision, size-limited packing, runt merge — deliberately
    duplicated line-for-line rather than sharing code with _chunk(), so
    _chunk()'s existing behavior (and second_brain/tests/test_pipeline.py's
    assertions, which import and call it directly) can never be disturbed by
    this change. tests/test_ingest_metadata.py asserts the *text* this
    produces is byte-identical to _chunk()'s own output for the same input —
    the real regression check, not just a claim in a docstring.

    Page attribution comes from character offsets recovered via
    text.split("\\n\\n"): split and "\\n\\n".join are exact inverses, so
    accumulating each piece's length (+2 for the separator) as we iterate
    gives every paragraph's true starting offset in the original text with no
    fragile substring search.

    A paragraph itself can span many pages — PDF text extraction often
    yields very few "\\n\\n" breaks (an entire multi-page section can arrive
    as one giant paragraph), so _split_oversized() alone ends up doing most
    of the real subdivision. The offset must therefore advance *within* a
    paragraph as its sub-pieces are consumed too, not just between
    paragraphs — the first cut of this function tagged every sub-piece of an
    oversized paragraph with the same page (the paragraph's own start),
    which on a real 58-page paper left all 156 chunks reporting page 1.
    _split_oversized() consumes sentences left-to-right and repacks them with
    a single space, so accumulating each sub-piece's length (+1 for that
    space) approximates its position within the paragraph closely enough to
    track which page it actually falls on.
    """
    raw_pieces = text.split("\n\n")
    units: list[tuple[str, int | None]] = []      # (paragraph piece, page)
    offset = 0
    for raw in raw_pieces:
        p = raw.strip()
        if p:
            sub_offset = 0
            for piece in _split_oversized(p, size):
                page = _page_for_offset(page_boundaries, offset + sub_offset)
                units.append((piece, page))
                sub_offset += len(piece) + 1
        offset += len(raw) + 2                    # +2 for the "\n\n" split() consumed

    chunks: list[tuple[str, list]] = []
    buf, buf_pages = "", []
    for u, page in units:
        if buf and len(buf) + len(u) + 2 > size:
            chunks.append((buf, buf_pages))
            buf, buf_pages = u, [page]
        else:
            buf = f"{buf}\n\n{u}" if buf else u
            buf_pages.append(page)
    if buf:
        chunks.append((buf, buf_pages))

    merged: list[tuple[str, list]] = []
    for c, pages in chunks:
        if merged and (len(c) < min_size or len(merged[-1][0]) < min_size) \
                and len(merged[-1][0]) + len(c) + 2 <= int(size * 1.5):
            merged[-1] = (f"{merged[-1][0]}\n\n{c}", merged[-1][1] + pages)
        else:
            merged.append((c, pages))

    out: list[tuple[str, dict]] = []
    for chunk_text, pages in merged:
        real_pages = [p for p in pages if p is not None]
        meta = {"page_start": min(real_pages), "page_end": max(real_pages)} if real_pages else {}
        out.append((chunk_text, meta))
    return out


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
        meta = _file_metadata(f)
        # PDFs go through the page-tracking path so citations can say where
        # in the book a passage lives; _chunk_with_pages is proven byte-
        # identical in its text output to plain _chunk() (see its own
        # docstring and tests/test_ingest_metadata.py), so this changes only
        # what metadata a chunk carries, never chunk boundaries themselves.
        ext = f.suffix.lower()
        if ext == ".pdf":
            try:
                text, boundaries = _read_pdf_with_pages(f)
            except Exception:
                text, boundaries = "", []
            if not text.strip():
                continue
            chunk_list = _chunk_with_pages(text, boundaries, size=chunk_size)
        elif ext == ".epub":
            # Same reasoning as the PDF branch: _chunk_with_chapters is
            # proven byte-identical in its text output to plain _chunk()
            # (see its docstring and tests/test_ingest_metadata.py) — this
            # only adds chapter metadata, real TOC-resolved, never a guess.
            try:
                text, boundaries = _read_epub_with_chapters(f)
            except Exception:
                text, boundaries = "", []
            if not text.strip():
                continue
            chunk_list = _chunk_with_chapters(text, boundaries, size=chunk_size)
        else:
            text = _read_text(f)
            if not text.strip():
                continue
            chunk_list = [(c, {}) for c in _chunk(text, size=chunk_size)]
        for i, (chunk, extra_meta) in enumerate(chunk_list):
            records.append({
                "source": str(f.relative_to(src)),
                "chunk_id": i,
                "text": chunk,
                "author": meta["author"],
                "title": meta["title"],
                "page_start": extra_meta.get("page_start"),
                "page_end": extra_meta.get("page_end"),
                "chapter": extra_meta.get("chapter"),
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
