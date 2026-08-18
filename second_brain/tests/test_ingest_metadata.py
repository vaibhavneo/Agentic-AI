"""Offline regression test for Milestone 2 Steps 3-4: file-level author/title
metadata and PDF page boundaries in ingest().

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

from second_brain.ingest import (
    _chapter_for_offset, _chunk, _chunk_with_chapters, _chunk_with_pages,
    _file_metadata, _flatten_toc, _page_for_offset, _read_epub,
    _read_epub_with_chapters, _read_pdf_with_pages, _read_text, ingest,
)

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

print("\n[_page_for_offset basic sanity]")
b = [0, 100, 250]                      # page 1 starts at 0, page 2 at 100, page 3 at 250
check("offset 0 is page 1", _page_for_offset(b, 0) == 1)
check("offset 99 is still page 1", _page_for_offset(b, 99) == 1)
check("offset 100 is page 2", _page_for_offset(b, 100) == 2)
check("offset 250 is page 3", _page_for_offset(b, 250) == 3)
check("offset past the last boundary is still the last page", _page_for_offset(b, 9999) == 3)
check("empty boundaries returns None", _page_for_offset([], 50) is None)

print("\n[_chunk_with_pages on a synthetic 3-page document — hand-verifiable]")
page1 = "Page one intro paragraph.\n\n" + ("word " * 100).strip()
page2 = "Page two continues.\n\n" + ("term " * 100).strip()
page3 = "Page three concludes.\n\n" + ("end " * 100).strip()
joined = "\n".join([page1, page2, page3])
boundaries = [0, len(page1) + 1, len(page1) + 1 + len(page2) + 1]
chunked = _chunk_with_pages(joined, boundaries, size=200, min_size=50)
check("every chunk got a page_start/page_end",
      all("page_start" in m and "page_end" in m for _, m in chunked), str(chunked[-1] if chunked else None))
check("page numbers stay within 1..3",
      all(1 <= m["page_start"] <= 3 and 1 <= m["page_end"] <= 3 for _, m in chunked))
check("page_start never exceeds page_end",
      all(m["page_start"] <= m["page_end"] for _, m in chunked))
check("the first chunk is attributed to page 1", chunked[0][1]["page_start"] == 1)
check("the last chunk is attributed to page 3 (or spans into it)",
      chunked[-1][1]["page_end"] == 3)

print("\n[regression: an oversized single paragraph spanning many pages must NOT all get page 1]")
# Real PDF extraction often yields almost no "\n\n" breaks — an entire multi-
# page section can arrive as one giant paragraph that _split_oversized()
# alone subdivides. The first cut of _chunk_with_pages() tagged every one of
# those sub-pieces with the page the *paragraph* started on — on a real
# 58-page paper this put page 1 on all 156 chunks, including the very last
# one. Build a single oversized "paragraph" (no "\n\n" anywhere in it) that
# spans 5 synthetic pages and confirm the resulting chunks' pages advance.
sentence = "This is one sentence about the topic at hand. "
giant_paragraph = sentence * 400                      # comfortably > CHUNK_SIZE, zero "\n\n"
five_pages = [giant_paragraph[i * (len(giant_paragraph) // 5):(i + 1) * (len(giant_paragraph) // 5)]
              for i in range(5)]
gp_boundaries, off = [], 0
for pg in five_pages:
    gp_boundaries.append(off)
    off += len(pg)
gp_chunked = _chunk_with_pages(giant_paragraph, gp_boundaries, size=200, min_size=50)
gp_pages = [m.get("page_start") for _, m in gp_chunked]
check("pages advance across an oversized single paragraph, not stuck at page 1",
      len(set(gp_pages)) > 1, str(gp_pages))
check("the last chunk of the oversized paragraph is NOT attributed to page 1",
      gp_chunked[-1][1].get("page_start", 1) > 1, str(gp_chunked[-1][1]))
check("pages are monotonically non-decreasing", gp_pages == sorted(gp_pages), str(gp_pages))

print("\n[_chunk_with_pages produces byte-identical TEXT to plain _chunk() — the real regression check]")
plain_chunks = _chunk(joined, size=200, min_size=50)
paged_texts = [t for t, _ in chunked]
check("same number of chunks", len(plain_chunks) == len(paged_texts),
      f"{len(plain_chunks)} vs {len(paged_texts)}")
check("chunk text is byte-for-byte identical, chunk by chunk",
      plain_chunks == paged_texts,
      "" if plain_chunks == paged_texts else
      f"first diff at index {next(i for i in range(min(len(plain_chunks), len(paged_texts))) if plain_chunks[i] != paged_texts[i])}")

print(f"\n[real pilot PDFs — old _read_text+_chunk vs new _read_pdf_with_pages+_chunk_with_pages: {PILOT_SRC}]")
pdf_files = sorted(PILOT_SRC.glob("*.pdf"))
checked_any = False
for f in pdf_files[:5]:                # a handful is enough; full corpus covered by the ingest() run above
    old_text = _read_text(f)
    if not old_text.strip():
        continue
    old_chunks = _chunk(old_text, size=1200)
    new_text, new_boundaries = _read_pdf_with_pages(f)
    new_chunks = _chunk_with_pages(new_text, new_boundaries, size=1200)
    new_texts = [t for t, _ in new_chunks]
    checked_any = True
    check(f"{f.name}: identical text output between old and new path",
          old_chunks == new_texts,
          "MATCH" if old_chunks == new_texts else
          f"{len(old_chunks)} vs {len(new_texts)} chunks — first diverges at "
          f"{next((i for i in range(min(len(old_chunks), len(new_texts))) if old_chunks[i] != new_texts[i]), 'length mismatch')}")
    pages_seen = [m.get("page_start") for _, m in new_chunks if m.get("page_start")]
    if pages_seen:
        check(f"{f.name}: page numbers are monotonically non-decreasing across chunks",
              pages_seen == sorted(pages_seen), str(pages_seen[:10]))
check("checked at least one real PDF from the pilot corpus", checked_any)

print("\n[_chapter_for_offset basic sanity]")
cb = [(0, "Intro"), (100, "Chapter 1"), (250, None), (400, "Chapter 2")]
check("offset 0 is Intro", _chapter_for_offset(cb, 0) == "Intro")
check("offset 99 is still Intro", _chapter_for_offset(cb, 99) == "Intro")
check("offset 100 is Chapter 1", _chapter_for_offset(cb, 100) == "Chapter 1")
check("offset 250 (untitled spine item) is None", _chapter_for_offset(cb, 250) is None)
check("offset 400 is Chapter 2", _chapter_for_offset(cb, 400) == "Chapter 2")
check("empty boundaries returns None", _chapter_for_offset([], 10) is None)

print("\n[_flatten_toc resolves the real book's chapter titles from its TOC, not a guess]")
ROBOTICS_EPUB = None
robotics_dir = Path("~/Desktop/Robotics").expanduser()
if robotics_dir.exists():
    epubs = sorted(robotics_dir.glob("*.epub"))
    if epubs:
        ROBOTICS_EPUB = epubs[0]

if ROBOTICS_EPUB is None:
    print(f"SKIP: no EPUB found under {robotics_dir} — chapter-resolution checks need a real EPUB")
else:
    import ebooklib
    from ebooklib import epub as _epub
    book = _epub.read_epub(str(ROBOTICS_EPUB))
    toc_map = _flatten_toc(book.toc)
    check("toc_map is non-empty for a real book with a real TOC", len(toc_map) > 0, f"{len(toc_map)} entries")
    spine_names = {it.get_name() for it in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
    check("every resolved chapter title maps to an actual spine file",
          all(href in spine_names for href in toc_map), str(set(toc_map) - spine_names))
    # A chapter-level TOC entry has no #fragment; its own sub-headings do and
    # share the same file — the chapter-level (first, no-fragment) title must
    # be the one that wins, not a sub-heading buried further down the TOC.
    frag_titles = set()
    def _walk_fragments(node):
        if isinstance(node, (list, tuple)):
            for n in node:
                _walk_fragments(n)
        elif getattr(node, "href", None) and "#" in node.href:
            frag_titles.add(node.title)
    _walk_fragments(book.toc)
    check("no sub-heading (fragment) title leaked into the chapter map",
          not (set(toc_map.values()) & frag_titles),
          str(set(toc_map.values()) & frag_titles))

    print(f"\n[_read_epub_with_chapters / _chunk_with_chapters on {ROBOTICS_EPUB.name}]")
    old_text = _read_epub(ROBOTICS_EPUB)
    old_chunks = _chunk(old_text, size=1200)
    new_text, boundaries = _read_epub_with_chapters(ROBOTICS_EPUB)
    check("joined text is identical between _read_epub and _read_epub_with_chapters",
          old_text == new_text, f"{len(old_text)} vs {len(new_text)} chars")
    new_chunked = _chunk_with_chapters(new_text, boundaries, size=1200)
    new_chunk_texts = [t for t, _ in new_chunked]
    check("chunk TEXT is byte-for-byte identical between old and new path",
          old_chunks == new_chunk_texts,
          "MATCH" if old_chunks == new_chunk_texts else
          f"{len(old_chunks)} vs {len(new_chunk_texts)} chunks — first diverges at "
          f"{next((i for i in range(min(len(old_chunks), len(new_chunk_texts))) if old_chunks[i] != new_chunk_texts[i]), 'length mismatch')}")
    with_chapter = [m for _, m in new_chunked if m.get("chapter")]
    check("most real chunks resolve a real chapter title (structural, not a guess)",
          len(with_chapter) > len(new_chunked) / 2,
          f"{len(with_chapter)}/{len(new_chunked)}")
    sample_titles = sorted({m["chapter"] for m in with_chapter})[:5]
    print(f"    sample chapter titles resolved: {sample_titles}")

print("\n[a chunk whose paragraphs span two chapters gets chapter: None, never a guess]")
part_a = "End of chapter one.\n\n" + ("alpha " * 80).strip()
part_b = "Start of chapter two.\n\n" + ("beta " * 80).strip()
joined = "\n\n".join([part_a, part_b])
cb2 = [(0, "Chapter One"), (len(part_a) + 2, "Chapter Two")]
# force a tiny size so a single output chunk is likely to straddle the boundary
straddled = _chunk_with_chapters(joined, cb2, size=len(joined) + 100, min_size=10)
check("a chunk spanning both chapters is not attributed to either one",
      any(m.get("chapter") is None for _, m in straddled) or len(straddled) > 1,
      str(straddled))

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
