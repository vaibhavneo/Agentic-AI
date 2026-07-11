# Example — Document Analysis

## Invocation
```json
{
  "goal": "Analyze 200 contract PDFs: extract parties, dates, obligations into a validated CSV",
  "memory_root": "contracts/memory",
  "stability_criteria": [
    {"id": "rows", "description": "one CSV row per document", "check": "test $(wc -l < out.csv) -eq 201"},
    {"id": "schema", "description": "all rows validate against field schema", "check": "python3 validate_csv.py out.csv"}
  ],
  "knowledge_sources": ["contracts/pdfs"],
  "max_cycles": 20
}
```

## Trace (abridged)
- C1: plan = ingest → extract sample(5) → validate → scale → CONTINUE
- C2: extractor on 5 docs; 2 date-format failures → CONTINUE
- C3: refine date parser (not rewrite); 5/5 pass → CONTINUE
- C4: run on all 200; 3 corrupt PDFs → flagged rows with "extraction_failed", not invented data → CONTINUE
- C5–6: checks pass ×2 → STABLE

## Contract point
Batch tasks stay atomic by sampling first (C2) — plan depth stays ≤3, and failures become next-cycle inputs rather than mid-cycle scope creep.
