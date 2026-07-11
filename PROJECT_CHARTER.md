# PROJECT CHARTER — AI Engineering Platform (AIOS)

**This is the constitution.** Any model, in any session, reads this first.
Rules here override defaults, habits, and model preferences. Amendments
require a new dated entry in `memory/decisions.md` citing the rule changed.

---

## 1. Vision

One personal AI Operating System that turns a large private knowledge base
(500+ books, papers, notes) into **completed real projects** — not answers.
The system learns what the user knows, tracks what they're building,
recommends the next action, executes atomic tasks through verified skills,
and remembers everything in files. Working implementations already exist and
are the proof: a grounded stock-analysis platform, a Vedic astrology engine,
a skill runtime, and the AIOS mission workspace.

## 2. Long-term objectives

1. AIOS at :8003 becomes the daily surface: missions → coach → execution (P1–P3 in IMPLEMENTATION_PLAYBOOK.md)
2. Every claim the system makes is evidence-backed (corpus provenance) or computed (never LLM-invented)
3. All capability is packaged as portable skills executable by any model through the runtime
4. The knowledge base grows: all 9 library categories + papers + finance PDFs as corpora
5. The system audits itself (self_check workflow) after every change

## 3. Non-negotiable architectural principles

These are load-bearing. Violating one is a bug even if the code works.

| # | principle | canonical statement |
|---|---|---|
| P1 | **Notebook-first memory** | Files are the only durable memory. Chat context is scratch. Any session resumes from files alone. |
| P2 | **Files are source of truth; databases are rebuildable indexes** | SQLite/`.md` views may always be dropped and regenerated (concepts.json → knowledge_cache.md; aios.db → mission files). |
| P3 | **Retrieve before reasoning** | Knowledge claims trace to retrieved chunks or computed facts — never to model priors alone. |
| P4 | **Grounding beats generation** | Numbers/facts a computation can supply are computed and handed to the LLM as ground truth ("cite, don't derive"). Proven twice: stock entry/stop/target formulas; vedic house-lords table. |
| P5 | **One atomic task per cycle** | The unit of work is small, file-scoped, and validatable in isolation. |
| P6 | **Evaluator before trust** | A stage is done when its deterministic check passes. Build the eval first. External ground truth (book values, hand arithmetic, classical tables) beats self-consistency. |
| P7 | **Honest flags over gamed scores** | Unsupported claims stay flagged; the fix is acquiring evidence, never editing the verdict. |
| P8 | **Model-agnostic execution** | Skills execute via manifests + contracts through the runtime. Reasoning enters only via adapters (`task_executor`, `agent_adapter`). No runtime code names a model or vendor (test-enforced). |
| P9 | **Scope is never guessed** | Retrieval requires a mission scope or explicit corpora override; no default corpus exists. Cross-corpus is opt-in and visibly flagged. |
| P10 | **Thin surfaces** | UIs and API layers wrap existing calls; business logic lives in skills/modules, never in a view or route handler. |

## 4. Philosophies (the "why" behind the rules)

- **Coding**: simplest correct thing with a documented upgrade path. Refinement over regeneration. Pure-python before dependencies (TF-IDF before embeddings — climb the RAG maturity ladder only when the current rung measurably fails). Framework-last: adopt orchestration frameworks only when the topology demands it.
- **Runtime**: contracts over conventions. 9-step lifecycle, typed failures, enforced memory permissions (sha1 snapshot diff vs manifest allowlists). See `brain/runtime/runtime.md`.
- **Memory**: memory ≠ one thing. state (overwrite) ≠ plan (edit) ≠ log (append-only one-liners) ≠ decisions (append-only, irreversible). Compress at write time; no file >200 lines; transcripts forbidden.
- **Skills**: define WHAT must happen, never WHICH model does it. Deterministic behavior → python driver; generative → agent-gated with schema-validated output (a hypothesis without a kill_test is rejected).
- **Workflows**: compose skills by contract (outputs→inputs, `$step.field` binding). Fail-fast, partial results returned.
- **Evaluation**: MUST metrics deterministic; discrimination required (an eval everything passes tests nothing); include negative cases; LLM-as-judge only for unscriptable quality metrics, with evidence recorded.

## 5. Repository conventions

```
<root>/                      workspace root (~/Desktop/Agentic AI)
  PROJECT_CHARTER.md         ← this file (read first)
  START_HERE.md              boot sequence for a new model
  AIOS_HANDBOOK.md           how the platform works
  IMPLEMENTATION_PLAYBOOK.md milestones P1+
  LESSONS.md                 extracted knowledge: tradeoffs, rejections, risks
  memory/                    THE live loop memory (D1): state/plan/log/decisions,
                             concepts.json, corpora/, missions/
  brain/                     the OS kernel
    runtime/                 dispatcher·registry·validator·executor·monitor·lifecycle
    skills/<id>/             manifest.json (+ contracts; flagship has full package)
    workflows/               *.workflow.json (executable) + WORKFLOWS.md
    console/                 operator console (:5052)
    tests/                   runtime/library/console suites
  second_brain/              knowledge pipeline: ingest/retrieve/gateway/
                             corpus_manager/concept_store/critic (+tests)
                             (distillation is the concept_distillation skill, D19)
  learn_agent/               AIOS product surface (:8003, /app) + AIOS_ARCHITECTURE.md
  model_adapters/            per-model interpretation guides
  stock_agent/ vedic_astro/ health-agent/  applications (own CLAUDE.md each)
```

- **Naming**: snake_case python; kebab-case ids (corpus ids, mission slugs, skill folder = snake_case id in manifest); `*.workflow.json` for workflows; tests `test_<area>.py`, runnable standalone (`python3 path/to/test.py`, exit 1 on failure, `ALL PASS` on success).
- **Ports**: 5050 vedic · 5051 stock · 5052 console · 8003 AIOS.
- **Skill manifest**: `manifest.json` is the canonical machine format (12 fields incl. `purpose`; normative spec: `SKILL_RUNTIME_SPEC.md`). YAML variants are NOT used — one format, one parser.
- **Skill authoring**: every NEW skill follows the canonical full-profile layout (`templates/skill/`, spec `SKILL_SDK.md`, process `SKILL_AUTHOR_GUIDE.md`) and must be VALID under `python3 -m aios_core.skill_sdk.validator <dir> full` with quality ≥85 before registration. Pre-SDK skills pass the reduced "core" profile and migrate to full opportunistically (rule R16).
- **Versioning**: semver per skill; breaking = schema type/requiredness, memory-contract loosening, step reordering. Registry constraints `>=X.Y.Z <A.B.C`.

## 6. Definition of Done (any change)

1. Deterministic check exists and passes (test file or criteria check)
2. All existing suites still green (see Validation Checklist in IMPLEMENTATION_PLAYBOOK.md)
3. Memory updated: log.md +1 line; state.md snapshot if a component changed; decisions.md only for irreversible choices
4. No memory file exceeds bounds; no logic added to a thin surface
5. Claims in the summary point at files/outputs, not adjectives

## 7. Engineering & testing standards

- Python 3.9 compatible (no `X | None` in FastAPI route signatures — runtime-evaluated; use `Optional`)
- Tests must be **idempotent** (wipe their scratch state; two proven incidents: console planner root reuse, stale index assumptions)
- Tests print evidence next to verdicts; every suite has ≥1 negative-path check
- New retrieval consumers go through `second_brain/gateway.py` — direct `Retriever` use outside the gateway/drivers is a violation of P9
- LLM keys resolve DeepSeek→Anthropic from app `.env` files (existing convention); never hardcode
