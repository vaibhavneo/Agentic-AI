---
name: rag_search
version: 1.0.0
description: Full retrieval-augmented answering — ingest→retrieve→ground→cite pipeline over a corpus. Use when answering questions FROM a document collection rather than from priors.
reference_impl: vedic_astro KB (format_context top_k=4) · second_brain retrieve→distill chain
---
# rag_search
**Purpose:** answers with receipts — every substantive claim carries its source.
**Inputs:** `question` · index (from book_ingestion) · `top_k` (default 4-5) · max context chars
**Outputs:** answer text + cited sources list; explicit "not found in corpus" when retrieval is empty.
**Contract:** retrieval BEFORE generation, retrieved text enters the prompt as labeled ground truth ("cite, don't derive") · answer may not contain claims absent from retrieved context + question · empty retrieval → say so (never fall back to priors silently) · maturity-ladder rule: upgrade retrieval (TF-IDF→vectors→GraphRAG) only when the current rung measurably fails.
