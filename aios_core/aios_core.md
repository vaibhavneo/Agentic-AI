# AIOS Core

Reusable AI operating-system infrastructure, separated from the applications
that use it. Version 1.0.0.

## Why this exists

Before extraction, the runtime lived in `brain/runtime/` and applications
imported it through a fragile `sys.path.insert(brain/runtime)` + bare-name
pattern (`from dispatcher import dispatch`), and re-implemented the same
"run a loop on a thread and poll" glue in more than one place. AIOS Core fixes
this: one engine, one stable public SDK, applications depend only on the SDK
(PROJECT_CHARTER.md P10, requirement #3).

## Layout

```
aios_core/
  __init__.py            # public SDK: skill · workflow · agent · memory · retrieval · mission
  runtime/               # the execution engine (moved from brain/runtime)
    dispatcher · registry · validator · executor · monitor · lifecycle
    drivers/             # python skill drivers (recursive_planner, echo, library_drivers)
  sdk/                   # the six stable APIs (facades over runtime + second_brain)
    skill · workflow · agent · memory · retrieval · mission
  aios_core.md           # this file
  MIGRATION.md           # legacy → SDK migration guide
  tests/test_aios_core.py
```

**What is core vs. not:** the runtime engine is core. The *skill library*
(`brain/skills/`) is content the core loads from a configured location
(`AIOS_SKILLS_DIR`, default `brain/skills/`) — it did not move, keeping blast
radius small. `second_brain/` (ingest/gateway/corpus_manager/critic) is the
knowledge layer the retrieval/memory SDKs wrap. Applications
(`learn_agent`, `brain/console`, `stock_agent`, …) sit above the SDK.

## The six stable APIs

Import them from the package root or `aios_core.sdk`:

```python
from aios_core import skill, workflow, agent, memory, retrieval, mission
```

| API | key calls | wraps |
|---|---|---|
| **skill** | `run(id, inputs, ctx)` · `list_skills()` · `get_manifest(id)` · `discover(tag=)` · `register()` | runtime dispatcher + registry |
| **workflow** | `run(wf)` · `run_loop(id, inputs)` · `run_file(path)` · `BackgroundRun` | dispatcher.run_workflow / run_loop |
| **agent** | `run(id, inputs, adapter=)` · `register_adapter(name, fn)` · `list_agent_skills()` · `make_context()` | dispatch with the reasoning-adapter seam |
| **memory** | `read(root, name)` · `list_files()` · `snapshot`/`diff` · `audit(root)` · `recent_metrics(n)` | monitor + memory_compression skill |
| **retrieval** | `retrieve(query, mission=/corpora=)` · `list_corpora()` · `ingest_corpus(id)` | second_brain gateway + corpus_manager |
| **mission** | `create(...)` · `get(slug)` · `list_all()` · `set_corpora()` · `run()` · `MissionStore` | files + SQLite mirror (extracted from learn_agent) |

Design rules the SDK preserves (unchanged from the charter):
- **Scope is never guessed** (P9): `retrieval.retrieve` requires a `mission` or `corpora`.
- **Model-agnostic** (P8): reasoning enters only via `agent`'s adapters / `context`.
- **Files are truth** (P1/P2): `mission` and `memory` are file-first; SQLite mirrors.
- **Permissions enforced**: writes go through skill dispatch; the dispatcher still
  fails a dispatch that writes outside its manifest allowlist (MEMORY_VIOLATION).

## Powering multiple applications

The regression suite instantiates both the Flask operator console and the
FastAPI AIOS app against the same core and answers `/api/health` from each —
concrete proof the core is application-agnostic. A new app follows the same
shape: `from aios_core import ...`, wire routes/UI on top, add nothing to the
runtime.

## Backward compatibility

`brain/runtime/*.py` remain as thin re-export shims: legacy
`from dispatcher import dispatch` (with `brain/runtime` on the path) and
`runtime.drivers.*` manifest entrypoints still resolve — and resolve to the
SAME module objects as `aios_core.runtime.*` (module identity preserved, so the
LESSONS-L7 arming/entrypoint hazard cannot reappear). See MIGRATION.md.
