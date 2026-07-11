# Adapter — GPT (any capable GPT-class model)

**Interpretation**: identical contracts apply; nothing here is
Claude-specific by design (test-enforced in brain/runtime). Follow
START_HERE.md verbatim.

**Watch for**: (1) this repo runs Python 3.9 — no modern-union type hints in
FastAPI signatures (LESSONS L8); (2) memory files have strict formats —
state.md is an overwritten snapshot, log.md is one line per change, never
paragraphs; (3) do not introduce new frameworks — see LESSONS §2 rejected
list; (4) tool/file conventions: tests are standalone scripts with exit
codes, not pytest-dependent.
**Recommended tasks**: same as Sonnet profile (atomic tasks) until several
validation cycles prove calibration, then milestone-scale.
**Prompting convention**: include the literal file paths of charter/handbook/
playbook in the system or first message; instruct "cite file paths for every
claim"; require the §V checklist output verbatim at session end.
**Known limitation**: adapters for generative skills expect a callable
`agent_adapter(manifest, inputs, context) -> dict matching output_schema`;
wire your client accordingly — outputs failing schema are rejected by the
runtime, which is correct behavior, not an integration bug.
