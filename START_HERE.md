# START_HERE — boot sequence for a new model

You are joining an in-progress AI Engineering Platform with **zero
conversation history**. The repository is the single source of truth.
Follow this sequence exactly; do not skip to coding.

## Boot sequence

1. **Read `PROJECT_CHARTER.md`** — the constitution. P1–P10 are non-negotiable.
2. **Read `AIOS_HANDBOOK.md`** — how the platform works and how parts interact.
3. **Read current memory** (this is where "what is true now" lives):
   - `memory/state.md` — component states, current iteration, known limits
   - `memory/plan.md` — open milestones and the queued Next Action
   - `memory/decisions.md` — D1–D12+: settled, irreversible choices
   - `memory/log.md` — one-line history (consult only when diagnosing)
4. **Read the roadmap**: `IMPLEMENTATION_PLAYBOOK.md` (milestones with DoD),
   and for design rationale `learn_agent/AIOS_ARCHITECTURE.md` (v1.1).
5. **Load the skill registry**: `brain/skills/registry.json`; runtime docs at
   `brain/runtime/runtime.md`. Verify the platform is healthy before changing it:
   ```
   python3 second_brain/tests/test_pipeline.py
   python3 second_brain/tests/test_gateway.py
   python3 brain/tests/test_runtime.py
   python3 brain/tests/test_library_skills.py
   python3 learn_agent/tests/test_aios_p0.py
   ```
   All must end `ALL PASS`. If not, fixing that IS your first mission.
6. **Execute the mission**: take the Next Action from `memory/plan.md` (or the
   next playbook milestone), work in atomic tasks, validate each with a
   deterministic check, and update memory files per the charter's Definition
   of Done. Your model-specific guidance: `model_adapters/<your-model>.md`.

## Orientation shortcuts

| question | answer lives in |
|---|---|
| Why is X built this way? | memory/decisions.md, then LESSONS.md |
| How do I add a skill? | brain/runtime/runtime.md § Adding a new skill |
| How does retrieval scope work? | AIOS_HANDBOOK.md §3; learn_agent/AIOS_ARCHITECTURE.md §6.5 |
| What are the app-specific rules? | CLAUDE.md at root and in stock_agent/ |
| What was tried and rejected? | LESSONS.md § Rejected alternatives |
| What must I verify after changes? | IMPLEMENTATION_PLAYBOOK.md §V |

## The two sentences that prevent most mistakes here

Files are the only memory, and every number or fact the system asserts must
be either computed or carry retrieval provenance. If you find yourself
letting an LLM state a figure, derive a lordship, guess a scope, or "improve"
a flagged verdict — stop; that exact class of bug has been found and fixed
in this repo before (LESSONS.md).
