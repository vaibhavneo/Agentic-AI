# Memory contract — healthpilot_heart_health_agent v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher).

- **root_param: "memory_root".** The caller supplies a scratch directory per
  dispatch. `write` and `append_only` are BOTH EMPTY — this is the
  dispatch-level proof that the Heart-Health Nutrition Agent specialist's chat tools are
  read-only. Structural enforcement already exists independently in
  `healthpilot/agents/tool_registry.py` (only `get_*`/`calculate_*`/
  `search_food`/`analyze_health_patterns`-style functions are exposed to
  chat at all); this manifest is a SECOND, dispatch-level layer on top of
  that — if this skill ever wrote a file under `memory_root`, VERIFY_MEMORY
  would catch it as `MEMORY_VIOLATION` and fail the dispatch. See
  `healthpilot/tests/integration/test_aios_core_retrofit.py`'s negative
  test for a live proof of the mechanism.
- **reads:** none tracked. HealthPilot's real state lives in SQLite, reached
  through HealthPilot's own HTTP server — outside aios_core's file-based
  memory model entirely (see the retrofit PR description for the full
  reasoning on why this skill's `root_param` doesn't point at HealthPilot's
  database).
- **writes:** none. A legitimate dispatch always produces zero
  `memory_changes`.
