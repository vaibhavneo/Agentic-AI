# Skill: brain_think v1.0.0

**Purpose:** The Central Orchestrator needs one uniform, typed way to hand an arbitrary task to brain/'s existing multi-agent system without reimplementing its planning/routing/execution logic.

**What it does:** Dispatch a free-text task to brain/'s own multi-agent orchestrator (Brain.think) and return its final answer.

| aspect | value |
|---|---|
| runtime | python → `aios_core.runtime.drivers.brain_think_driver:run` (mechanical, no adapter seam) |
| execution steps | RESOLVE API KEY → INVOKE BRAIN → WRAP RESULT |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | stateless — no reads, no writes |
| dependencies | none |
| failure modes | `EXECUTION_ERROR` if `Brain.think` itself raises |
| success metrics | [evaluation_contract.md](evaluation_contract.md) E1–E3 |
| version | 1.0.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | core `>=1.0.0 <2.0.0` |

**Invocation mechanism:** in-process (D20) — brain/ has no bare top-level
module name collision with `feynman_agent`, the only other in-process app.

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
