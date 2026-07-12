# Skill: central_orchestrator v1.0.0

**Purpose:** A person or another system has one free-text task and 5 independently-built AI applications; this skill picks the right one, validates that choice against the real roster, and falls back to brain/'s general-purpose orchestrator when nothing clearly fits (H-O3).

**What it does:** Route a free-text task to the right one of 5 independent AI apps (brain, feynman_agent, stock_agent, health_agent, vedic_astro) and dispatch it through that app's own wrapper skill.

| aspect | value |
|---|---|
| runtime | python → `aios_core.runtime.drivers.central_orchestrator_driver:run` (deterministic scaffolding + adapter-gated routing decision) |
| execution steps | LOAD APP ROSTER → CLASSIFY → VALIDATE CHOICE → DISPATCH |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | stateless — reads `orchestrator/apps.json` (a repo config file, not a memory root); no writes |
| dependencies | `brain_think` (the fallback target, H-O3) |
| failure modes | `NOT_EXECUTABLE` (no adapter); `EXECUTION_ERROR` (dispatched skill fails, or a structured-input app is chosen without `app_inputs`) |
| success metrics | [evaluation_contract.md](evaluation_contract.md) E1–E4 |
| version | 1.0.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | core `>=1.0.0 <2.0.0` |

**The one model-naming file:** `orchestrator/fable_adapter.py` wires Claude
Fable 5 as this skill's `agent_adapter` — never this skill or its driver
(P8).

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
