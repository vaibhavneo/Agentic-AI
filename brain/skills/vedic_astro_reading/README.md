# Skill: vedic_astro_reading v1.0.0

**Purpose:** The Central Orchestrator needs one uniform, typed way to hand birth data to vedic_astro/'s existing chart + reading pipeline; vedic_astro/'s own `agents/` package collides with brain/'s internals if imported in-process (D20), so this skill reaches it over HTTP instead, keeping the app's geocode->reading sequence as internal glue (H-O4).

**What it does:** Dispatch a birth place/date/time to vedic_astro/'s 6-agent deep prediction engine (over its running HTTP server) and return the full multi-section reading.

| aspect | value |
|---|---|
| runtime | python → `aios_core.runtime.drivers.vedic_astro_reading_driver:run` (mechanical, no adapter seam) |
| execution steps | RESOLVE ENDPOINTS → GEOCODE → READING (SSE) → WRAP RESULT |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | stateless — no reads, no writes |
| dependencies | none |
| failure modes | `EXECUTION_ERROR` on a failed geocode, an upstream `error` event, or a reading stream ending with zero sections |
| success metrics | [evaluation_contract.md](evaluation_contract.md) E1–E4 |
| version | 1.0.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | core `>=1.0.0 <2.0.0`; requires vedic_astro/'s server running (default `http://localhost:5050`) |

**Invocation mechanism:** HTTP (D20) — vedic_astro/ owns an `agents/`
package that collides with brain/'s bare top-level import name.

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
