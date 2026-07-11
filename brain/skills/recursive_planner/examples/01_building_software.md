# Example — Building Software

## Invocation (conforms to input_schema.json)
```json
{
  "goal": "Build a backtesting engine whose leak-test, drawdown, and dSR tests all pass",
  "memory_root": "stock_agent/memory",
  "stability_criteria": [
    {"id": "tests", "description": "engine test suite green", "check": "python3 tests/test_backtest_engine.py"},
    {"id": "book_truth", "description": "reproduces Hilpisch/de Prado reference numbers", "check": "python3 tests/test_backtest_engine.py | grep -c FAIL | grep -q '^0$'"}
  ],
  "knowledge_sources": ["~/Desktop/AI/Applied AI in Finance"],
  "max_cycles": 15
}
```

## Trace (abridged — real execution from this workspace)
- C1: plan phases engine→strategies→sizing (plan.md) → CONTINUE
- C2: atomic task 1.2 `run_vectorized_backtest` with internal `.shift(1)`; leak-test PASSES → CONTINUE
- C3: dSR vs book value 3.255≈3.26 → validated → CONTINUE
- C7: user-reported MaxDD>1 bug → re-plan (relative drawdown); fix + test → CONTINUE
- C8: all criteria pass, 2nd consecutive → **STABLE**

## Why the contract mattered
The MaxDD bug was caught by M-metric discipline (validate with evidence), and
the fix was a *refinement* of one function, not a rewrite (Q5).
