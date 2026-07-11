# Evaluation — AI Engineering Pack

Domain eval rules (PROJECT_CHARTER.md P6: build the deterministic check first;
external ground truth beats self-consistency).

## Deterministic (MUST)
- **concept_map integrity**: every returned edge connects two returned nodes
  (no dangling edges); node/edge counts reproduce concepts.json by hand for a
  fixed filter. Checked in tests/test_pack.py.
- **retrieval scope honored**: pack workflows retrieve only from declared
  corpora; a scope-less query raises NoScopeError (P9).
- **pack conformance**: PackManager.conformance("ai_engineering").ok is True.

## Quality (LLM-judged, evidence recorded)
- Design reviews and pattern-mapping outputs (future architect/teacher skills)
  are graded against the concept store's supported concepts, never priors.

## Ground truth sources
- The 10 verified mental models in memory/concepts.json (critic-scored).
- Book values already used as anchors elsewhere (dSR 3.255≈3.26, Kelly ≈4.5).
