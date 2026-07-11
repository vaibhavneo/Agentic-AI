# AIOS HANDBOOK — internal engineering documentation

Audience: an engineer (human or model) who has read PROJECT_CHARTER.md and
needs to work on the platform. Deep dives live in the linked files; this is
the connective tissue.

---

## 1. What AIOS is and why

A Personal AI Operating System: missions (real projects) sit at the center;
knowledge (corpora), execution (skills via a runtime), verification (critic/
evaluator), and memory (files) orbit them. It exists because chat-based AI
loses context, invents facts, and finishes nothing — AIOS counters each:
files for memory (P1), provenance for facts (P3/P9), atomic validated tasks
for finishing (P5/P6).

Origin: it federates systems that already worked — the Second Brain loop
(second_brain/), the Skill Runtime (brain/runtime/), and the learn_agent
tutor — rather than rebuilding them. Full design: `learn_agent/AIOS_ARCHITECTURE.md` (v1.1).

## 2. Component map & interaction

```
:8003 learn_agent  ──/app──▶ AIOS shell (missions, ⌘K, corpus-badged search)
  aios_api.py  ── thin routes; imports ONLY the aios_core SDK
  agent.py     ── tutor LLM (legacy /ask, kept for back-compat)
  teacher_adapter.py ── wires agent.py's LLM as the `teacher` skill's adapter;
                 teach()=teach→upsert→critic loop; served at /api/teach (M-P2a)
        │
        ▼  from aios_core import skill · workflow · agent · memory · retrieval · mission
aios_core/  ── AIOS CORE (reusable infrastructure; see aios_core/aios_core.md)
  sdk/       ── the six STABLE public APIs (apps depend only on these)
  skill_sdk/ ── Skill Authoring SDK: validator (9-stage) + quality score +
               Part-10 benchmark; docs SKILL_SDK.md / SKILL_AUTHOR_GUIDE.md
  runtime/   ── dispatcher (9-step lifecycle) · registry · validator ·
               executor (python|agent) · monitor (metrics.jsonl) · drivers/
        │ skill.run("id", inputs, context)  →  dispatch
        ▼
brain/skills/*     manifests + contracts (the skill LIBRARY the core loads;
                   AIOS_SKILLS_DIR configurable, default brain/skills/)
        │ retrieval.retrieve(query, mission=/corpora=)
        ▼
second_brain/gateway.py  scope→fan-out→normalize→merge→dedup→confidence→
                          provenance→(widen, flagged)   [wrapped by retrieval SDK]
        ▼
memory/corpora/<id>/chunks.json   independent indexes (corpus_manager.py)
memory/missions/<slug>/           mission.json + state/plan/log/decisions/notes/questions
memory/*.md, concepts.json        global loop memory + verified mental models
```

Backward compatibility: `brain/runtime/*.py` remain as re-export shims so legacy
`from dispatcher import ...` and `runtime.drivers.*` entrypoints still work. New
code imports `aios_core`. Migration table: `aios_core/MIGRATION.md`.

## 3. How retrieval works (the gateway, §6.5 of the architecture)

- **No default corpus.** Scope = mission's declared `corpora` or an explicit
  override; otherwise `NoScopeError` ("scope is never guessed").
- Per-corpus TF-IDF (smoothed idf — see LESSONS.md L3) → min-max normalize
  per corpus (raw scores aren't comparable) → × corpus `reliability` →
  merged rank → 8-gram shingle dedup (survivor keeps ALL corpus provenances)
  → hit = {text, source, corpus[], raw/normalized score, confidence, cross_corpus}.
- `cross_corpus: true` on the mission allows widening when scope under-fills
  top_k; every widened hit is flagged and the UI renders it amber.
- Corpora: `memory/corpora/registry.json` via `second_brain/corpus_manager.py`
  (register/ingest/adopt_index/stats). Current: curated-wiki 96 · ai-books
  25,812 · personal-notes 127 · finance + llm-books registered, on-demand.

## 4. How memory is updated

Two levels, same discipline (memory_contract.md of recursive_planner is the
canonical spec):
- **Global loop memory** `memory/`: state.md (overwrite snapshot), plan.md
  (edit/prune), log.md (append 1 line/cycle), decisions.md (append,
  irreversible), concepts.json (source of truth; knowledge_cache.md is a
  rendered view via `concept_store.render_markdown()`).
- **Per-mission memory** `memory/missions/<slug>/`: identical file set;
  mission.json holds corpora scope. The UI renders these files — it never
  stores its own copy (P2, P10).
- Writes happen through skills; the dispatcher diff-checks actual file
  changes against the manifest's write/append_only patterns and fails the
  dispatch on violation (MEMORY_VIOLATION).

Concept provenance: every `sources[]` entry is `{corpus, source}`. The critic
(`second_brain/critic.py`) scores each concept deterministically
(0.5·retrieval_support + 0.5·source_corroboration), corpus-aware; concepts
from `workspace` provenance can be flagged but never laundered to
"supported" (P7).

## 5. How missions execute

1. Creation (`POST /api/missions`) requires ≥1 valid corpus; scaffolds the
   memory root + SQLite mirror rows.
2. Execution = `run_loop("recursive_planner", inputs)`: each dispatch is ONE
   cycle of the 8-step execution contract (`brain/skills/recursive_planner/
   execution_contract.md`). Mechanical steps run in the python driver;
   the atomic task itself is delegated to `context["task_executor"]` — that
   is where a model plugs in.
3. STABLE requires all stability criteria passing on 2 consecutive cycles;
   BLOCKED names exactly what the requester must supply; every cycle appends
   one log line and rewrites the state snapshot.

## 6. How agents collaborate

"Agents" are skills + adapters (see roster table in AIOS_ARCHITECTURE.md §3.2).
Deterministic agents (retriever, critic, evaluator, memory auditor, planner
mechanics) are python drivers — same behavior under any model. Generative
agents (teacher, architect, code_generator, hypothesis_generation,
concept_distillation) are agent-type skills: the runtime refuses to run them
without an adapter, and validates whatever the adapter returns against the
output schema — a weaker model cannot silently degrade a contract.
Coordination is the dispatcher (`run_workflow` for chains, `run_loop` for
cycles); "which agent is working" is read from metrics.jsonl, not simulated.

## 7. How to build a new application on the platform

1. Define the goal as a mission (falsifiable, ≥3 tasks, corpora declared).
2. Knowledge first: register/ingest a corpus if the domain isn't covered.
3. Capability next: author the skill via the Skill SDK — copy
   `templates/skill/`, follow SKILL_AUTHOR_GUIDE.md, ship only when
   `aios_core.skill_sdk.validator` says VALID (full profile) and quality ≥85.
   Deterministic behavior → python driver; generative → agent-type with
   strict output schema.
4. Compose a workflow file; add a dispatch test with ≥1 failure path.
5. Surface last: thin API route + UI panel that only renders skill outputs.
6. Ship = Definition of Done in the charter (checks green, memory updated).

## 8. Operational knowledge

- Start AIOS: `cd learn_agent && python3 server.py` (:8003; /app shell; legacy tutor at /)
- Operator console: `cd brain && python3 console/app.py` (:5052)
- Self-audit: run the `self_check` workflow (tests + critic + memory audit through the runtime itself)
- All suites: see Validation Checklist (IMPLEMENTATION_PLAYBOOK.md §V)
- First query against ai-books pays a ~seconds index-load; retrievers are
  cached per corpus per process (gateway `_retrievers`)
