---
name: retrieve_context
version: 1.0.0
description: Fetch only the chunks relevant to the current task from an ingested index. Use before ANY reasoning step that makes knowledge claims (Step 2 of recursive_planner).
reference_impl: second_brain/retrieve.py
---
# retrieve_context
**Purpose:** replace "recall from priors" with "retrieve from evidence." Bounded context injection.
**Inputs:** `query` (str, required) · `index_path` (default memory/index/chunks.json) · `top_k` (≤5, default 5)
**Outputs:** ranked `[{score, source, text}]`; empty list for no-signal queries (never fabricated hits).
**Contract:** results ranked descending; scores reproducible (pure TF-IDF, no RNG); gibberish → []; caller must cite `source` for any claim built on a chunk. Budget: ≤3 queries per atomic task.
**Failure mode guarded:** false-positive retrieval — validated by test "gibberish query returns empty."
