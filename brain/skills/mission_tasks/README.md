# Skill: mission_tasks v1.0.0

**Purpose:** The UI must let a person add and check off mission tasks without ever writing a memory file directly — this is the one dispatcher-enforced, idempotent, plan.md-only write path that makes that safe.

**What it does:** Create a mission task or set its done/todo status by editing exactly one file, plan.md, at the line the Mission SDK already treats as that task's identity.

| aspect | value |
|---|---|
| runtime | python → `aios_core.runtime.drivers.mission_tasks_driver:run` (fully mechanical, no adapter seam) |
| execution steps | RESOLVE OPERATION → LOCATE OR VALIDATE TASK → APPLY IDEMPOTENTLY → WRITE IF CHANGED |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | root=`memory_root` (the mission's own dir) · write: `["plan.md"]` ONLY · no append-only, no other reads |
| dependencies | none |
| failure modes | `EXECUTION_ERROR` (bad/missing op-specific field, unknown `task_id`); `MEMORY_VIOLATION` if a write ever lands outside `plan.md` (dispatcher-enforced, never triggered by correct code) |
| success metrics | [evaluation_contract.md](evaluation_contract.md) E1–E5 |
| version | 1.0.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | any executor honoring the runtime contracts (charter P8); core `>=1.0.0 <2.0.0` |

**Idempotent by design:** `create` dedupes by exact task text; `set_done`
no-ops when the target state already holds. Both make the write path safe
against retries/double-clicks — `changed:false` means nothing was written,
regardless of HTTP status.

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
