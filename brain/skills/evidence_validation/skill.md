---
name: evidence_validation
version: 1.0.0
description: Verify claims against retrievable or computable evidence and assign calibrated confidence. Use on every distilled concept, hypothesis, or recommendation before it enters durable memory.
reference_impl: second_brain/critic.py scoring + flags · stock_agent grounding (formula-reproducible numbers) · vedic house-lords table
---
# evidence_validation
**Purpose:** the gate between "generated" and "believed" — nothing enters the concept store unverified.
**Inputs:** claim {statement, claimed_sources[]} · evidence backends (retrieval index, deterministic computations)
**Outputs:** {confidence 0-1, status, evidence[], flags[]} written back onto the claim record.
**Contract:** deterministic scoring where possible (retrieval_support + source_corroboration) · claimed-but-unretrieved sources FLAGGED explicitly · non-index provenance (workspace experience, memory refs) marked "cannot verify by retrieval" — kept, flagged, never laundered into "supported" · low confidence triggers evidence acquisition (ingest more sources), never verdict editing · numeric claims validated by recomputation, not text similarity.
