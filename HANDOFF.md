# HANDOFF — Fable architecture sessions → any future model

Conversation history is assumed deleted. The repository is the single source
of truth. **Entry point: [START_HERE.md](START_HERE.md).**

## The knowledge-transfer package (created 2026-07-05)

| document | role |
|---|---|
| [PROJECT_CHARTER.md](PROJECT_CHARTER.md) | constitution: principles P1–P10, philosophies, conventions, Definition of Done |
| [AIOS_HANDBOOK.md](AIOS_HANDBOOK.md) | how the platform works: components, retrieval, memory, missions, agents, building new apps |
| [START_HERE.md](START_HERE.md) | 6-step boot sequence for a fresh session |
| [IMPLEMENTATION_PLAYBOOK.md](IMPLEMENTATION_PLAYBOOK.md) | milestones M-P1a…M-P3 + M-K with DoD/exit/risks/rollback + §V Validation Checklist |
| [LESSONS.md](LESSONS.md) | extracted knowledge: 10 lessons, 10 rejected alternatives, risks, best practices |
| [model_adapters/](model_adapters/) | Opus · Sonnet · GPT · Gemini guidance + production prompts (architecture identical across models) |
| [brain/workflows/WORKFLOWS.md](brain/workflows/WORKFLOWS.md) | 3 executable + 9 recipe workflows, skill-referencing only |
| brain/skills/*/README.md | per-skill cards (generated from manifest.json — edit manifest+skill.md, not the README) |
| [learn_agent/AIOS_ARCHITECTURE.md](learn_agent/AIOS_ARCHITECTURE.md) | full v1.1 design (corpus manager amendment) |
| [brain/runtime/runtime.md](brain/runtime/runtime.md) | runtime v1.1.0: lifecycle, manifest spec, extension points, authoring checklist |
| [MIGRATION_EXECUTION_PLAN.md](MIGRATION_EXECUTION_PLAN.md) | Learning-Agent → AIOS Core migration handoff: boundary audit, WP‑0…8, human gates H1–H6 (+ OPUS_MIGRATION_PROMPT.md, SONNET_TASK_TEMPLATES.md) |
| memory/decisions.md | ADRs D1–D20 (append-only) |
| memory/state.md · plan.md · log.md | live truth · open work · compressed history |

## Current state in one line
Skill runtime v1.1.0 + 10-skill library + operator console (:5052) + AIOS P0
live (:8003/app: 5 corpora, retrieval gateway, 2 seeded missions, ⌘K shell) —
7/7 test suites green. Next milestone: **M-P1a (coach triggers)**.

## Remaining human decisions (cannot be made by a model)
1. Approve start of M-P1a (or reorder P1 items)
2. Corpus expansion order for M-K (finance PDFs vs remaining book categories)
3. React migration timing for the shell (deferred, not rejected — LESSONS §2)
4. Keep or retire the legacy tutor UI at :8003/ once /app reaches parity
5. ~~distill.py DeepSeek path~~ — RESOLVED 2026-07-10 (H5): retired (D19); distillation is the model-agnostic `concept_distillation` skill
6. Stock agent outcome-check scheduling (manual today; a sweep would grow the
   hit-rate data that feeds grounded confidence)
