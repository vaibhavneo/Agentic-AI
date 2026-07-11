# CAPABILITY DESCRIPTOR — advisory skill metadata

`capability.json` is an **optional** per-skill descriptor that sits ABOVE the
execution manifest. It carries routing hints, semantic I/O roles, and quality
requirements for a **capability router / scheduler / marketplace** — a layer
above the dispatcher. Implementation: `aios_core/skill_sdk/capability.py`.

## The one rule (why it is NOT part of manifest.json)

| | `manifest.json` | `capability.json` |
|---|---|---|
| role | the EXECUTION contract | ADVISORY metadata |
| read by | the dispatcher (runtime) | a router/scheduler ABOVE the runtime — **never the dispatcher** |
| model names? | **forbidden** (P8: no runtime-parsed artifact names a vendor; test-enforced) | allowed — as config DATA, like `MODEL_EXECUTION_GUIDE.md` names models as docs |

Putting `preferred_models` in the manifest would name vendors in a
runtime-parsed file → violate P8 and zero the portability quality score.
Keeping it in a separate advisory file preserves both. The dispatcher never
imports `capability` (test-enforced), so the execution path stays model-blind;
the descriptor only informs *which adapter an orchestrator chooses* — it never
changes skill behavior. Reasoning still enters solely through the adapter seam
(P8). The router reads model names FROM descriptors; `capability.py` hardcodes
none (also test-enforced).

## Schema

```jsonc
{
  "name": "<skill_id>",              // MUST == manifest.id     (V10b)
  "version": "1.0.0",                // MUST == manifest.version (V10c)
  "execution": {
    "preferred_models": ["claude-opus", "claude-sonnet", "gpt-5", "gemini"],
    "reasoning_level": "high",       // low | medium | high | xhigh
    "estimated_tokens": 8000         // advisory cost hint for a scheduler
  },
  "inputs":  ["mission", "memory", "context"],          // SEMANTIC roles, above the
  "outputs": ["plan", "artifacts", "updated_memory"],   // JSON schemas (for matching)
  "quality_requirements": {
    "min_test_coverage": 90,         // VERIFIED (real, see below), not asserted
    "deterministic": true,           // cross-checked against skill.md (V10d)
    "requires_human_approval": false,// HITL policy gate (consulted by orchestrators)
    "coverage_target": "pkg.module.driver",     // optional: module to measure
    "coverage_command": "python3 path/to/tests" // optional: how to exercise it
  }
}
```

## Verification (P6: claims are checked, not trusted)

The validator folds an OPTIONAL stage **V10** into `validate_skill` — only when
`capability.json` exists; skills without one are unaffected:

- **V10a** schema conforms · **V10b/c** name+version match the manifest ·
  **V10e** reasoning_level is a known level.
- **V10d** — a `deterministic: true` claim MUST be backed by a determinism
  statement in `skill.md` (honesty check; caught recursive_planner's descriptor
  asserting determinism its contract didn't document — fixed by documenting the
  truthful mechanical/executor split, not by editing the verdict).
- **V10f** (opt-in, `check_quality_requirements(run_coverage=True)`) — REAL
  line coverage of `coverage_target` measured via stdlib `trace` while
  `coverage_command` runs, compared to `min_test_coverage`. No new dependency;
  recursive_planner measures **100% (62/62 driver lines)**.

## Advisory router

`capability.route(skill_dirs, min_reasoning=)` → `{preferred_models,
needs_human_approval, est_tokens, skipped}`. Purely advisory: it unions the
descriptors' `preferred_models`, sums token estimates, and surfaces
human-approval gates so an orchestrator can pick an adapter and decide whether
to pause for approval. The dispatcher/runtime never consult it.

## When to add one

Optional. Add a descriptor when a skill will be scheduled/routed across models,
gated for human approval, or matched semantically in a marketplace. Pure
library skills invoked directly through `skill.run()` don't need one. The
template is `templates/skill/capability.json`.

CLI: `python3 -m aios_core.skill_sdk.capability <skill_dir> [--coverage]`.
