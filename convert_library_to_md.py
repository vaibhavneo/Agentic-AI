#!/usr/bin/env python3
"""Batch-convert PDF/EPUB books in selected Desktop folders to full-text markdown
files dropped into the Obsidian vault under raw/library/<category>/.

Idempotent: skips a book if its output .md already exists.
"""
import os
import re
import sys
import json
import zipfile
from pathlib import Path

import pypdf
from bs4 import BeautifulSoup

DESKTOP = Path("/Users/vaibhavgupta/Desktop")
VAULT_RAW = Path("/Users/vaibhavgupta/Documents/brain/Vaibhav's Second Brain/raw/library")

CATEGORIES = {
    "Agentic AI": "agentic-ai",
    "LLMs": "llms",
    "Generative AI ": "generative-ai",
    "Mathematics for Machine Learning & Deep Learning": "math-for-ml-dl",
    "Machine Learning": "machine-learning",
    "Deep Learning": "deep-learning",
    "NLP": "nlp",
    "Computer Vision": "computer-vision",
    "Reinforcement Learning": "reinforcement-learning",
}

LOG_PATH = Path("/Users/vaibhavgupta/Desktop/Agentic AI/convert_library_log.jsonl")


def slugify(name: str) -> str:
    name = re.sub(r"\.(pdf|epub)$", "", name, flags=re.I)
    name = re.sub(r"[^\w\s-]", "", name).strip()
    name = re.sub(r"[\s_]+", "-", name)
    return name[:150] or "untitled"


def extract_pdf_text(path: Path) -> str:
    reader = pypdf.PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            text = f"[extraction error on page {i}: {e}]"
        parts.append(text)
    return "\n\n".join(parts)


def extract_epub_text(path: Path) -> str:
    parts = []
    with zipfile.ZipFile(path) as z:
        html_files = sorted(
            [n for n in z.namelist() if n.lower().endswith((".html", ".xhtml", ".htm"))]
        )
        for name in html_files:
            try:
                raw = z.read(name).decode("utf-8", errors="ignore")
                soup = BeautifulSoup(raw, "html.parser")
                text = soup.get_text(separator="\n")
                parts.append(text)
            except Exception as e:
                parts.append(f"[extraction error in {name}: {e}]")
    return "\n\n".join(parts)


def log(entry: dict):
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def process_category(folder_name: str, slug: str):
    src_dir = DESKTOP / folder_name
    out_dir = VAULT_RAW / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    if not src_dir.exists():
        print(f"SKIP (no dir): {folder_name}")
        return

    files = sorted(
        [p for p in src_dir.rglob("*") if p.suffix.lower() in (".pdf", ".epub")]
    )
    print(f"\n=== {folder_name} -> {slug} ({len(files)} files) ===")

    for i, path in enumerate(files, 1):
        out_name = slugify(path.stem) + ".md"
        out_path = out_dir / out_name
        if out_path.exists() and out_path.stat().st_size > 200:
            print(f"[{i}/{len(files)}] SKIP exists: {path.name}")
            continue

        print(f"[{i}/{len(files)}] {path.name}")
        try:
            if path.suffix.lower() == ".pdf":
                text = extract_pdf_text(path)
            else:
                text = extract_epub_text(path)
        except Exception as e:
            print(f"  ERROR: {e}")
            log({"file": str(path), "status": "error", "error": str(e)})
            continue

        title = path.stem
        frontmatter = (
            "---\n"
            f"title: \"{title.replace(chr(34), chr(39))}\"\n"
            f"category: {slug}\n"
            f"source_path: \"{path}\"\n"
            "type: book-fulltext\n"
            "---\n\n"
        )
        text = text.encode("utf-8", errors="replace").decode("utf-8")
        try:
            out_path.write_text(frontmatter + text, encoding="utf-8")
            log({"file": str(path), "status": "ok", "out": str(out_path), "chars": len(text)})
        except Exception as e:
            print(f"  WRITE ERROR: {e}")
            log({"file": str(path), "status": "write_error", "error": str(e)})


def main():
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    for folder_name, slug in CATEGORIES.items():
        if only and slug not in only:
            continue
        process_category(folder_name, slug)
    print("\nDONE.")


if __name__ == "__main__":
    main()
