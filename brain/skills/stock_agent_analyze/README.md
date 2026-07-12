# Skill: stock_agent_analyze v1.0.0

**Purpose:** The Central Orchestrator needs one uniform, typed way to hand a ticker to stock_agent/'s existing 7-agent pipeline; stock_agent/'s own package names collide with brain/'s internals if imported in-process (D20), so this skill reaches it over HTTP instead.

**What it does:** Dispatch a stock ticker to stock_agent/'s 7-agent financial analysis pipeline (over its running HTTP server) and return the final BUY/SELL/HOLD result.

| aspect | value |
|---|---|
| runtime | python → `aios_core.runtime.drivers.stock_agent_analyze_driver:run` (mechanical, no adapter seam) |
| execution steps | RESOLVE ENDPOINT → CALL OVER HTTP (SSE) → WRAP RESULT |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | stateless — no reads, no writes |
| dependencies | none |
| failure modes | `EXECUTION_ERROR` on connection failure, an upstream `error` SSE event, or a stream ending without a `result` event |
| success metrics | [evaluation_contract.md](evaluation_contract.md) E1–E3 |
| version | 1.0.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | core `>=1.0.0 <2.0.0`; requires stock_agent/'s server running (default `http://localhost:5051`) |

**Invocation mechanism:** HTTP (D20) — stock_agent/ owns `agents/`/`tools/`
packages that collide with brain/'s bare top-level import names.

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
