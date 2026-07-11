# Example — Research

## Invocation
```json
{
  "goal": "Produce an evidence-cited comparison of agent orchestration frameworks, every claim traceable to an ingested source",
  "memory_root": "research/memory",
  "stability_criteria": [
    {"id": "coverage", "description": "≥4 frameworks compared on ≥5 axes", "check": "grep -c '^| ' report.md — table rows ≥ 4"},
    {"id": "citations", "description": "every claim row cites a source file", "check": "python3 check_citations.py report.md"}
  ],
  "knowledge_sources": ["wiki/books/agentic-ai"]
}
```

## Trace (abridged)
- C1: ingest sources → index built → CONTINUE
- C2: retrieve per-framework chunks; draft comparison axes → CONTINUE
- C3: fill table; citation check FAILS on 2 rows (claims from priors, not retrieval) → CONTINUE
- C4: re-retrieve for the 2 rows; one claim unsupported → row flagged "no source found," not deleted-and-invented → CONTINUE
- C5: all checks pass ×2 → STABLE

## Contract point
Step 2 (retrieve-before-reasoning) is what caught the two prior-knowledge claims; Q4 (evidence honesty) kept the unsupported row flagged.
