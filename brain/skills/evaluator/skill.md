---
name: evaluator
version: 1.0.0
description: Build the deterministic check BEFORE trusting any output — test suites, ground-truth reproductions, validation reports. Use before shipping any pipeline stage or claim.
reference_impl: second_brain/tests/test_pipeline.py (20 checks) · stock_agent leak-test/dSR-vs-book · vedic 12-ascendant lordship eval
---
# evaluator
**Purpose:** "works" is a test result, not a feeling — quality claims without evals are anecdotes.
**Inputs:** artifact/stage to validate · ground truth (book values, hand arithmetic, classical tables, synthetic constructions)
**Outputs:** runnable test file + generated report (validation_report.md pattern: table of stage|test|result|detail).
**Contract:** prefer external ground truth (book reproduces, hand-computed cases) over self-consistency · include discrimination checks (an eval everything passes tests nothing) · include negative cases (gibberish→empty, losing-strategy→rejected) · deterministic exit code so loops can gate on it.
**Proven catches:** impossible MaxDD (32×), look-ahead leak, losing-strategy-confirms-BUY, LLM-invented house lords.
