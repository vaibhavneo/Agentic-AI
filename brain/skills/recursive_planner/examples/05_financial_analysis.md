# Example — Financial Analysis

## Invocation
```json
{
  "goal": "Produce a grounded BUY/SELL/HOLD assessment for PLTR where every numeric level is formula-computed, never LLM-invented",
  "memory_root": "stock_agent/memory",
  "stability_criteria": [
    {"id": "grounded", "description": "entry/stop/target hand-reproducible from price+ATR formulas", "check": "python3 -c 'grounding determinism check'"},
    {"id": "edge", "description": "recommendation cites a positive-Sharpe strategy or downgrades to LOW", "check": "assert grounding==strategy implies sharpe>0"}
  ],
  "knowledge_sources": ["Applied AI in Finance library"],
  "max_cycles": 10
}
```

## Trace (real, abridged)
- C1: backtest 7 strategies on 3y history → CONTINUE
- C2: LLM verdict wrapped by ground_prediction(); stop=1.5×ATR, target=2:1 RR → CONTINUE
- C3: eval found losing strategy "confirming" a BUY → refine: positive-edge filter; conviction downgrades to LOW when no profitable strategy agrees → CONTINUE
- C4: determinism + edge checks pass ×2 → STABLE

## Contract point
Planning Rule 7 (honest flags): PLTR's BUY got grounding=none and LOW conviction rather than a gamed confirmation.
