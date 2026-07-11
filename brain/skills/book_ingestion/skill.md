---
name: book_ingestion
version: 1.0.0
description: Convert source documents (md/txt/pdf/epub) into a chunked, retrievable index. Use as the first stage before any retrieval or distillation over a document corpus.
reference_impl: second_brain/ingest.py · vedic_astro/knowledge/ingest.py (10,358 chunks/23 books)
---
# book_ingestion
**Purpose:** knowledge is only usable once it is chunked and indexed — raw files are not memory.
**Inputs:** `source_dir` · extensions filter · `chunk_size` (~1200 chars, paragraph-boundary packing)
**Outputs:** index JSON {source_dir, n_files, chunks:[{source, chunk_id, text}]} + ingest stats.
**Contract:** chunk on paragraph boundaries (never mid-sentence splits at exact byte counts) · no text loss (validated: every paragraph findable in chunk stream) · idempotent (re-run replaces index) · curated-first ordering (signal density over volume — 36 wiki pages before 456 raw books).
**Scale note:** JSON store until size/concurrency demands SQLite (documented upgrade path, D4).
