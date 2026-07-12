# validation_report.md — Pipeline Validation
<!-- Generated 2026-07-11 by second_brain/tests/test_pipeline.py. Overwritten each run. -->

**Result: 20/20 pass**

| stage | test | result | detail |
|---|---|---|---|
| ingest | chunks stay near size limit | PASS | max=925 |
| ingest | no paragraph lost in chunking | PASS |  |
| ingest | index well-formed (files>0, chunks>0) | PASS | 36 files / 96 chunks |
| ingest | every chunk has source+text keys | PASS |  |
| retrieve | returns results for known topic | PASS |  |
| retrieve | results ranked descending | PASS |  |
| retrieve | top hit topically correct | PASS | agentic-ai/agentic-design-patterns.md |
| retrieve | gibberish query returns empty (no false positives) | PASS |  |
| store | ≥10 concepts migrated | PASS | n=10 |
| store | all concepts carry full schema | PASS |  |
| store | relationship graph non-empty | PASS | edges=8 |
| store | all relationship targets exist (no dangling edges) | PASS |  |
| store | upsert preserves critic verdict (no silent reset) | PASS |  |
| critic | every concept has confidence in [0,1] | PASS |  |
| critic | every concept has a verification status | PASS |  |
| critic | scores discriminate (not all identical) | PASS | distinct=[0.28, 0.81, 1.0] |
| critic | non-index provenance flagged | PASS | 3 concept(s) |
| critic | report file exists | PASS |  |
| loop | stability check runs and reports all stages | PASS |  |
| loop | system currently STABLE | PASS | {"ingest": true, "retrieval": true, "distill": true, "n_models": 10} |
