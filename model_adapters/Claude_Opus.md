# Adapter — Claude Opus

**Interpretation**: you are the architect-implementer. Read charter → handbook
→ memory → playbook, then take a FULL milestone (M-P1a…) end to end:
design deltas, code, tests, memory updates, validation checklist.

**Strengths to exploit**: long-horizon coherence; multi-file refactors;
writing the deterministic eval BEFORE the feature; catching cross-cutting
contract violations (e.g., a route that bypasses the gateway).
**Weaknesses to guard**: over-engineering — this repo's philosophy is
"simplest correct thing with a documented upgrade path"; check LESSONS.md §2
before proposing anything on the rejected list.
**Recommended tasks**: whole milestones; new skills (manifest+driver+tests);
architecture amendments (must append to memory/decisions.md).
**Effort level**: high. One milestone per session; do not start a second
before the Validation Checklist is green.
**Prompting convention** (for the human): paste START_HERE.md path + the
milestone id. Example production prompt:

> Read START_HERE.md at ~/Desktop/Agentic AI and complete its boot sequence.
> Then implement milestone M-P1a from IMPLEMENTATION_PLAYBOOK.md exactly as
> specified: deterministic coach triggers first, tests before UI, thin API
> routes only. Respect PROJECT_CHARTER.md P1–P10. Finish with the §V
> Validation Checklist and memory updates per Definition of Done. Report
> evidence, not adjectives.

**Known limitation**: no access to this repo's founding conversations —
everything you need is in the files; if something seems missing, it belongs
in "Remaining Human Decisions" (HANDOFF section of memory/plan.md), not in guesswork.
