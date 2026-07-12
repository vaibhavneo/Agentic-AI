# Skill: health_agent_analyze v1.0.0

**Purpose:** The Central Orchestrator needs one uniform, typed way to hand vitals to health-agent/'s existing analysis pipeline; health-agent/'s own package names collide with brain/'s internals if imported in-process (D20), so this skill reaches it over HTTP instead.

**What it does:** Dispatch free-text vitals (e.g. 'HR=88 BP=145/92 SpO2=94') to health-agent/'s threshold + LLM trend analysis (over its running HTTP server) and return the structured result.

| aspect | value |
|---|---|
| runtime | python → `aios_core.runtime.drivers.health_agent_analyze_driver:run` (mechanical, no adapter seam) |
| execution steps | RESOLVE ENDPOINT → CALL OVER HTTP → WRAP RESULT |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | stateless — no reads, no writes |
| dependencies | none |
| failure modes | `EXECUTION_ERROR` on connection failure or an upstream error (status or embedded `error` key) |
| success metrics | [evaluation_contract.md](evaluation_contract.md) E1–E3 |
| version | 1.0.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | core `>=1.0.0 <2.0.0`; requires health-agent/'s server running (default `http://localhost:8787`) |

**Invocation mechanism:** HTTP (D20) — health-agent/ owns `agents/`/`tools/`
packages that collide with brain/'s bare top-level import names.

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
