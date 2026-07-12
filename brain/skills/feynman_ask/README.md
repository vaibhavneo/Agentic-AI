# Skill: feynman_ask v1.0.0

**Purpose:** The Central Orchestrator needs one uniform, typed way to hand a physics question to feynman_agent/'s multi-turn tutor without reimplementing its retrieval + session-history logic.

**What it does:** Dispatch a physics question to feynman_agent/'s Feynman-technique QM tutor and return its cited answer.

| aspect | value |
|---|---|
| runtime | python → `aios_core.runtime.drivers.feynman_ask_driver:run` (mechanical, no adapter seam) |
| execution steps | RESOLVE SESSION → INVOKE TUTOR → WRAP RESULT |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | stateless — no reads, no writes |
| dependencies | none |
| failure modes | `EXECUTION_ERROR` if `session.ask` itself raises |
| success metrics | [evaluation_contract.md](evaluation_contract.md) E1–E3 |
| version | 1.0.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | core `>=1.0.0 <2.0.0` |

**Invocation mechanism:** in-process (D20) — feynman_agent/'s only bare
top-level module (`agent`, singular) does not collide with brain/'s
internals, the only other in-process app.

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
