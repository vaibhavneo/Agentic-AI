# Example — Book Synthesis

## Invocation (this is the reference implementation's own cycle 1)
```json
{
  "goal": "Distill 10 evidence-grounded reusable mental models from the ingested book library",
  "memory_root": "memory",
  "stability_criteria": [
    {"id": "ingest", "description": "index built", "check": "python3 second_brain/loop.py → ingest:true"},
    {"id": "retrieval", "description": "3 test queries relevant", "check": "loop.py → retrieval:true"},
    {"id": "models", "description": "≥10 concepts stored", "check": "loop.py → n_models≥10"}
  ],
  "knowledge_sources": ["wiki/books"]
}
```

## Trace (real)
- C1: ingest 36 files → 96 chunks → CONTINUE
- C1: TF-IDF retrieve; 3/3 relevant → CONTINUE
- C1: distill 10 models FROM retrieved chunks → knowledge_cache → CONTINUE
- C2: loop check all-pass ×2 → STABLE
- C3 (hardening): critic verified 9/10 supported; 1 honestly flagged unsupported-by-index

## Contract point
The critic (evidence_validation skill) found that 1 of 10 "book-derived" models actually rested on workspace experience — exactly what Q4 exists to surface.
