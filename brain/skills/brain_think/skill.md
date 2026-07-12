# brain_think — behavioral contract

## Purpose (mandatory)
Give the Central Orchestrator (and any other caller) one typed, dispatcher-
enforced way to hand a free-text task to brain/'s existing multi-agent
orchestrator, without reaching into brain/'s internals directly.

## Business problem (mandatory)
Without this skill, dispatching to brain/ means importing `Brain` directly
and hoping the caller handles sys.path scoping, API-key resolution, and
error shapes consistently — brittle, undocumented, and untyped. This skill
makes that one call typed, metered (runtime monitor), and swappable (a
future brain/ rewrite only has to keep this contract, not its call sites).

## Inputs (mandatory)
- `task` (required): the free-text task, passed to `Brain.think` verbatim.
- `auto_critique` (optional, default false): brain/'s own quality-gate flag.

## Outputs (mandatory)
- `app`: always `"brain"` (lets a caller confirm which app actually answered).
- `answer`: brain/'s final answer string, unmodified.

## Determinism (mandatory)
**Not deterministic** — brain/'s own orchestrator makes its own model calls
internally. This skill's OWN logic (API-key resolution, instantiation,
result wrapping) is fully mechanical; it has no adapter seam of its own and
names no model (brain/'s internal model choice is brain/'s concern, not
this skill's).

## Hidden-assumption audit (mandatory)
- Assumes `brain/` is importable once `brain/` itself (not the repo root) is
  added to sys.path — verified empirically (D20); a namespace-package
  collision occurs if the repo root is used instead.
- Assumes an `ANTHROPIC_API_KEY` is available (via `context["anthropic_api_key"]`
  or the environment) — brain/'s own `Brain.__init__` handles a missing key
  by producing brain/'s own error string, not by raising here.
- Does not catch exceptions from `Brain.think` — a real internal failure
  surfaces as `EXECUTION_ERROR`, not a swallowed empty answer.

## Preconditions / Postconditions (mandatory)
- Pre: `task` is a non-empty string.
- Post: output validates against `output_schema.json`; no memory files
  changed (stateless).

## When NOT to use (optional but recommended)
For the other 4 apps, use their own wrapper skill instead
(`stock_agent_analyze`, `health_agent_analyze`, `vedic_astro_reading`,
`feynman_ask`). For automatic app selection from a free-text task, use
`central_orchestrator`, which dispatches to this skill as its own fallback
(H-O3).
