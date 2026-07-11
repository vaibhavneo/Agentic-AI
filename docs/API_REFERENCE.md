# AIOS API Reference

The current API surface, extracted from source. Every signature, field, and
payload below was verified against the actual repository files cited beside it
— nothing here is invented. Items that are designed but not yet implemented
are explicitly labelled **PLANNED**.

Two surfaces exist:
- **SDK (Python)** — `from aios_core import skill, workflow, agent, memory, retrieval, mission`. The stable, in-process interface (`aios_core/sdk/`).
- **HTTP** — FastAPI routes served by `learn_agent/server.py` on **:8003**. Thin wrappers over the SDK (charter P10).

Ports: 8003 AIOS · 5052 operator console · 5050 vedic · 5051 stock.

---

## 1. Skill dispatch — `skill.run`

Source: `aios_core/sdk/skill.py`, `aios_core/runtime/dispatcher.py`, `aios_core/runtime/lifecycle.py`.

```python
from aios_core import skill
result = skill.run(skill_id: str, inputs: dict, context: dict | None = None,
                   version: str = "*")   # -> DispatchResult
```

Other `skill` functions: `list_skills() -> list[str]` · `get_manifest(skill_id, version="*") -> dict` · `discover(query="", tag="") -> list[dict]` · `resolve_dependencies(skill_id, include_optional=False) -> list[str]` · `register(entry, persist=False)`.

**`DispatchResult`** (`.to_dict()` shape — `aios_core/runtime/lifecycle.py`):

```json
{
  "ok": true,
  "skill_id": "retrieve_context",
  "version": "2.0.0",
  "output": { "hits": [], "n": 0, "scope": ["curated-wiki"], "widened": false, "confidence": 0.0 },
  "failure": null,
  "failure_detail": "",
  "failed_step": null,
  "metrics": { "elapsed_ms": 5.1, "attempts": 1, "retries": 0 },
  "memory_changes": [],
  "violations": []
}
```

`skill.run` never raises for skill-level problems — inspect `ok` / `failure`.
Typed `failure` codes (`aios_core/runtime/lifecycle.py`): `SKILL_NOT_FOUND`,
`MANIFEST_INVALID`, `INPUT_INVALID`, `MEMORY_ROOT_INVALID`, `NOT_EXECUTABLE`,
`EXECUTION_ERROR`, `OUTPUT_INVALID`, `MEMORY_VIOLATION`, `DEPENDENCY_UNRESOLVED`.

---

## 2. Skill manifest shape

Source: `SKILL_RUNTIME_SPEC.md` §3, `brain/skills/recursive_planner/manifest.json`.
The manifest is the only file the runtime reads. 12 required keys:

```json
{
  "id": "concept_map",
  "name": "Concept Map",
  "version": "1.0.0",
  "description": "Build the concept sub-graph from the verified concept store.",
  "purpose": "Turn the flat concept store into a navigable graph.",
  "tags": ["knowledge", "graph"],
  "inputs":  { "schema": "input_schema.json" },
  "outputs": { "schema_inline": { "type": "object", "required": ["nodes","edges","n"] } },
  "memory": {
    "root_param": null,
    "read": [], "write": [], "append_only": [], "immutable": []
  },
  "execution": {
    "contract": "skill.md",
    "steps": ["LOAD_STORE", "FILTER", "BUILD_GRAPH"],
    "retries": 0,
    "runtime": { "type": "python", "entrypoint": "pkg.module:function" }
  },
  "dependencies": [ { "id": "retrieve_context", "version": ">=1.0.0 <2.0.0", "optional": true } ],
  "evaluation": { "contract": "evaluation_contract.md", "must": ["E1"] }
}
```

- `inputs`/`outputs`: either `{"schema": "file.json"}` or `{"schema_inline": {...}}`.
- `execution.runtime.type`: `"python"` (needs `entrypoint`) or `"agent"` (needs a caller-supplied `context["agent_adapter"]`, else `NOT_EXECUTABLE`).
- `memory.root_param`: name of the input holding the memory root, or `null` for stateless skills.
- Optional sibling file `capability.json` (advisory; **not** part of the manifest, never read by the dispatcher) — see `CAPABILITY_DESCRIPTOR.md`.

---

## 3. Mission API

Source: `aios_core/sdk/mission.py` (SDK) and `learn_agent/aios_api.py` (HTTP).
Files are the source of truth; SQLite (`learn_agent/data/aios.db`) is a mirror.

### SDK

```python
from aios_core import mission
mission.create(title, mtype, goal, corpora, cross_corpus=False, tasks=None) -> dict
mission.get(slug) -> dict
mission.list_all() -> list[dict]
mission.set_corpora(slug, corpora=None, cross_corpus=None) -> dict
mission.run(slug, stability_criteria, max_cycles=10, context=None, job=None) -> BackgroundRun
# mission.MissionStore(missions_dir=, db_path=) for a custom-located store
```
Creation requires ≥1 corpus that resolves in the corpus registry (else `ValueError`).

### `mission.json` (on disk, `memory/missions/<slug>/mission.json`)

```json
{
  "id": "build-ai-stock-analysis-platform",
  "title": "Build AI Stock Analysis Platform",
  "type": "build",
  "goal": "Grounded BUY/SELL/HOLD where every number is formula-computed and tracked",
  "corpora": ["finance", "curated-wiki"],
  "cross_corpus": true,
  "status": "active",
  "created": "2026-07-05"
}
```

`mission.get()` / `GET /api/missions/{slug}` return the file **plus** computed
fields: `tasks` (parsed from `plan.md`: `[{id, done, description}]`),
`progress` (0–100, checked/total), `memory_files` (the mission's `*.md`),
`questions` (from `questions.md`).

### HTTP routes (all under `/api`, port 8003; `learn_agent/aios_api.py`)

| method + path | body / params | returns |
|---|---|---|
| `GET /api/missions` | — | `{ "missions": [ …mission objects… ] }` |
| `POST /api/missions` | `{title, goal, type?, corpora[], cross_corpus?, tasks?}` | created mission, or `{error}` 400 |
| `GET /api/missions/{slug}` | — | full mission object, or `{error}` 404 |
| `PATCH /api/missions/{slug}/corpora` | `{corpora?, cross_corpus?}` | updated mission |
| `GET /api/missions/{slug}/memory/{name}` | `name` = a `*.md` file | `{name, content}` (traversal-blocked) |

**Create payload example** (`POST /api/missions`):
```json
{ "title": "Learn Reinforcement Learning", "type": "learn",
  "goal": "Explain and implement 3 RL algorithms with working code",
  "corpora": ["ai-books"], "cross_corpus": false,
  "tasks": ["Read the value-iteration chapter", "Implement Q-learning", "Evaluate on a gridworld"] }
```

**PLANNED:** `POST /api/missions/{slug}/run` (execute a mission's loop over HTTP)
is milestone **M-P1b** and does **not** exist yet. Mission execution is
currently only available via the SDK `mission.run()` (returns a `BackgroundRun`,
§7).

---

## 4. Corpus registry

Source: `second_brain/corpus_manager.py`, `memory/corpora/registry.json`, SDK `aios_core/sdk/retrieval.py`.

### SDK
```python
from aios_core import retrieval
retrieval.list_corpora() -> list[dict]
retrieval.get_corpus(corpus_id) -> dict
retrieval.register_corpus(corpus) -> dict     # corpus = {id, name, description, source_dirs[], reliability?, tags?, ingest_profile?}
retrieval.ingest_corpus(corpus_id) -> dict    # {corpus, files, chunks}
retrieval.adopt_index(corpus_id, existing_index) -> dict
```

### Registry entry (`memory/corpora/registry.json`, `registry_version: "1.0.0"`)
```json
{
  "id": "curated-wiki",
  "name": "Curated Wiki",
  "description": "36 verified book summary pages",
  "source_dirs": ["/abs/path/to/wiki/books"],
  "reliability": 1.0,
  "tags": ["books", "verified"],
  "ingest_profile": { "extensions": [".md", ".txt"], "chunk_size": 1200 },
  "index_path": "/abs/path/to/memory/corpora/curated-wiki/chunks.json",
  "stats": { "files": 36, "chunks": 96, "last_ingested": "2026-07-08T18:20:12" }
}
```
`index_path` and `stats` are derived by the manager (do not hand-set).
`reliability` (0–1) weights this corpus in the gateway (§5).

### HTTP routes
| method + path | body | returns |
|---|---|---|
| `GET /api/corpora` | — | `{ "corpora": [ …entries… ] }` |
| `POST /api/corpora` | a corpus dict (see above) | registered entry, or `{error}` 400 |
| `POST /api/corpora/{cid}/ingest` | — | `{corpus, files, chunks}`, or `{error}` 404 |

---

## 5. Retrieval Gateway

The single retrieval entry point. Scope is never guessed (charter P9): pass a
`mission` (its declared corpora) or explicit `corpora`, else `NoScopeError`.

### SDK — `retrieval.retrieve` (`aios_core/sdk/retrieval.py`)
```python
from aios_core import retrieval
retrieval.retrieve(query: str, mission: str | None = None,
                   corpora: list[str] | None = None,
                   cross_corpus: bool | None = None, top_k: int = 5) -> dict
# raises retrieval.NoScopeError if neither mission nor corpora is given
```
> Naming note: the SDK parameter is `mission`; the underlying
> `second_brain/gateway.py::retrieve` and the HTTP `/api/search` use
> `mission_id`. This inconsistency is real and tracked as **M-Q1d** — documented
> here rather than papered over.

### Result shape (`second_brain/gateway.py`)
```json
{
  "hits": [
    { "text": "…chunk text…", "source": "agentic-ai/agentic-design-patterns.md",
      "corpus": ["curated-wiki"], "raw_score": 0.41, "normalized_score": 1.0,
      "confidence": 1.0, "cross_corpus": false, "chunk_id": 0 }
  ],
  "n": 1,
  "scope": ["curated-wiki"],
  "scope_kind": "override",
  "widened": false,
  "confidence": 1.0
}
```
`corpus` is a list (dedup keeps every provenance of a merged hit).
`cross_corpus: true` marks a hit pulled in by opt-in widening (`cross_corpus`
on the mission). Gibberish → `{hits: [], n: 0, …}` (honest empty).

### HTTP — `GET /api/search`
Query params: `q` (≥3 chars), `mission_id?`, `corpora?` (comma-separated),
`cross_corpus?`. Returns the result shape above; `{error}` 400 on short query
or no scope, 404 on unknown mission/corpus. Example:
`GET /api/search?q=agent+memory&corpora=ai-books,curated-wiki`

---

## 6. Memory update interface

Source: `aios_core/sdk/memory.py`, `aios_core/runtime/dispatcher.py`, memory_contract of `recursive_planner`.

**There is no free-form "write a memory file" API — by design (charter P1/P2).**
Memory is updated **only** through skill dispatch: a skill declares a `memory`
allowlist in its manifest, and the dispatcher sha1-snapshots the `memory_root`
before/after execution and **fails the dispatch (`MEMORY_VIOLATION`)** if any
file changed outside `write ∪ append_only`. So the "update interface" is:
dispatch a skill whose contract permits the write.

Read/observe side — the `memory` SDK:
```python
from aios_core import memory
memory.read(root, name) -> str            # one file; traversal-safe (basename only)
memory.list_files(root, pattern="*.md") -> list[str]
memory.audit(root, max_lines=200) -> dict # runs the memory_compression skill: {compliant, issues, files_audited}
memory.snapshot(root) -> {relpath: sha1}  # change-detection primitive
memory.diff(before, after) -> list[str]
memory.metrics_path() -> Path
memory.recent_metrics(n=30) -> list[dict] # tail of metrics.jsonl (see §7 line shape)
```

`memory.audit` example result:
```json
{ "compliant": true, "issues": [], "files_audited": 8 }
```

HTTP read access is per-mission only: `GET /api/missions/{slug}/memory/{name}`
(§3). There is no HTTP endpoint that writes memory.

---

## 7. Workflow execution

Source: `aios_core/sdk/workflow.py`, `aios_core/runtime/dispatcher.py`, `brain/workflows/*.workflow.json`.

```python
from aios_core import workflow
workflow.run(workflow: dict, context=None, registry=None) -> dict
workflow.run_loop(skill_id, inputs, context=None, registry=None, max_dispatches=50) -> dict
workflow.load(path) -> dict
workflow.run_file(path, context=None, registry=None) -> dict
workflow.BackgroundRun()   # .start_loop(skill_id, inputs, ...) -> bool; .running; .status() -> dict
```

### Workflow file shape (`brain/workflows/corpus_qa.workflow.json`)
```json
{
  "name": "corpus_qa",
  "description": "ingest a corpus, then answer a question scoped to it.",
  "steps": [
    { "step": "ingest", "skill": "book_ingestion", "inputs": { "corpus_id": "curated-wiki" } },
    { "step": "answer", "skill": "rag_search",
      "inputs": { "question": "What separates an AI agent from a plain chatbot?",
                  "corpora": ["curated-wiki"] } }
  ]
}
```
A step's `inputs` may bind a prior step's output with `"$stepname.field.path"`.

### `run` (composition) return
```json
{ "name": "corpus_qa", "ok": true,
  "results": [ { "step": "ingest", "ok": true, "output": {"chunks": 96} },
               { "step": "answer", "ok": true, "output": {"found": true} } ] }
```
Fail-fast: on a failed step, `{ "name", "ok": false, "failed_step": "answer", "results": […partial…] }`.

### `run_loop` (cyclic skills) return
```json
{ "ok": true, "final_status": "STABLE",
  "cycles": [ { "ok": true, "output": { "cycle": 1, "status": "CONTINUE" } },
              { "ok": true, "output": { "cycle": 2, "status": "STABLE" } } ] }
```
`final_status` ∈ `STABLE | BLOCKED | ABORTED | DISPATCH_CAP` (or a typed failure
code if a dispatch failed). `BackgroundRun.status()` wraps the same result:
`{ running, label, final_status, result }`.

### `metrics.jsonl` line (one per dispatch; `aios_core/runtime/monitor.py`)
```json
{ "ts": "2026-07-08T18:21:02", "skill": "memory_compression", "version": "1.0.0",
  "ok": true, "elapsed_ms": 4.5, "attempts": 1, "retries": 0, "confidence": null,
  "memory_changes": [], "artifacts": [], "failure": null }
```

---

## 8. Mission Control read API (`/api/mc/*`)

Source: `learn_agent/mission_control_api.py` (read-only aggregation over the SDK; port 8003).
`GET /api/mc/summary` bundles all panels; granular endpoints:
`GET /api/mc/{missions | priorities | learning-progress | knowledge-growth |
project-status | insights | health | memory | decisions | actions | timeline}`,
plus `POST /api/mc/health/run-self-check` (runs the `self_check` workflow).
Full behavior: `learn_agent/MISSION_CONTROL_GUIDE.md`.

---

## 9. Planned / not-yet-implemented (do not call these)

| item | status | source |
|---|---|---|
| `POST /api/missions/{slug}/run` (HTTP mission execution) | **PLANNED** — M-P1b | IMPLEMENTATION_PLAYBOOK.md |
| Coach API (`/api/coach`, accept/dismiss) | **PLANNED** — M-P1a (a 3-rule proto-coach exists at `/api/mc/actions` only) | IMPLEMENTATION_PLAYBOOK.md |
| Task write endpoints (`POST/PATCH /api/missions/{slug}/tasks`) | **PLANNED** — M-P1c | IMPLEMENTATION_PLAYBOOK.md |
| `/api/graph`, `/api/teach` | **PLANNED** — M-P2 | IMPLEMENTATION_PLAYBOOK.md |
| Skill marketplace install / deprecation / compatibility-matrix | **PLANNED (⧗)** — designed only | SKILL_MARKETPLACE.md |
| Capability router consumed by a scheduler | **advisory only** — `capability.route()` exists; nothing auto-routes on it yet | CAPABILITY_DESCRIPTOR.md |

**Naming/quality debt referenced above:** `mission` vs `mission_id` (M-Q1d),
`metrics.jsonl` retention + test-noise (M-Q1b) — see PLATFORM_IMPROVEMENT_REPORT.md.
