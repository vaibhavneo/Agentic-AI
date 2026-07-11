# Migration Guide — runtime → AIOS Core

Version 1.0.0 · the runtime moved from `brain/runtime/` to `aios_core/runtime/`
and gained a public SDK. **Nothing you have today breaks** — legacy imports are
preserved by shims — but new code should use the SDK.

## TL;DR

```python
# OLD (still works via shims, but deprecated):
import sys; sys.path.insert(0, ".../brain/runtime")
from dispatcher import dispatch, run_loop
from registry import Registry
from monitor import METRICS_PATH

# NEW (canonical):
from aios_core import skill, workflow, memory
result   = skill.run("some_skill", inputs, context)
loop     = workflow.run_loop("recursive_planner", inputs)
metrics  = memory.metrics_path()
```

## Mapping table

| Old | New |
|---|---|
| `from dispatcher import dispatch` | `from aios_core import skill` → `skill.run(id, inputs, ctx)` |
| `from dispatcher import run_workflow` | `from aios_core import workflow` → `workflow.run(wf)` |
| `from dispatcher import run_loop` | `workflow.run_loop(id, inputs)` |
| `from registry import Registry` | `skill.list_skills()` / `skill.get_manifest()` / `skill.discover()` (or `aios_core.runtime.registry.Registry` for discovery objects) |
| `from monitor import METRICS_PATH` | `memory.metrics_path()` / `memory.recent_metrics(n)` |
| hand-rolled thread + status dict around `run_loop` | `workflow.BackgroundRun` |
| `from second_brain.gateway import retrieve` | `from aios_core import retrieval` → `retrieval.retrieve(q, mission=/corpora=)` |
| `from second_brain import corpus_manager` | `retrieval.list_corpora()` / `retrieval.ingest_corpus()` / `retrieval.register_corpus()` |
| mission CRUD in `learn_agent/aios_api.py` | `from aios_core import mission` → `mission.create/get/list_all/set_corpora/run` (or a `MissionStore`) |
| manifest entrypoint `runtime.drivers.X:fn` | `aios_core.runtime.drivers.X:fn` (auto-updated; legacy string still resolves) |

## What changed under the hood

- **Runtime internals** now use relative imports (`from .lifecycle import ...`);
  import them as a package (`import aios_core.runtime`), not by bare name.
- **Skill library location** is configurable: `AIOS_SKILLS_DIR` env var
  (default `brain/skills/`). The library did not move.
- **metrics.jsonl** now lives at `aios_core/runtime/metrics.jsonl` (history was
  copied forward). `memory.metrics_path()` always points at the live file.
- **Manifest entrypoints** were rewritten to `aios_core.runtime.drivers.*`.

## Compatibility guarantees & removal timeline

- The `brain/runtime/*.py` shims are **kept indefinitely** for v1.x; they
  re-export the canonical modules and preserve module identity.
- New applications MUST import from `aios_core` (charter P10, requirement #3).
- A future v2.0.0 MAY remove the shims — that would be a breaking change
  requiring a `memory/decisions.md` entry and a major version bump per the
  charter's versioning rules.

## How to verify a migration

Run the two suites that exercise the seam end to end:

```
python3 aios_core/tests/test_aios_core.py     # SDK + shims + multi-app
python3 brain/tests/test_runtime.py           # runtime contracts
```
Both must print `ALL PASS`.
