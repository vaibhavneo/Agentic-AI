# OPUS MIGRATION PROMPT — whole-milestone sessions

Production prompts for Claude Opus sessions executing the Opus-scoped work
packages of MIGRATION_EXECUTION_PLAN.md (WP‑1, WP‑4). Convention source:
`model_adapters/Claude_Opus.md` — one milestone per session, do not start a
second before the Validation Checklist is green.

**Human: before pasting, confirm the gate decisions** (plan §5): H1 for WP‑1;
H5 + WP‑1 complete for WP‑4. Paste ONE prompt per session.

---

## Prompt A — WP‑1 (M-P1a Coach service)

> Read START_HERE.md at ~/Desktop/Agentic AI and complete its boot sequence.
> Then execute WP‑1 of MIGRATION_EXECUTION_PLAN.md — milestone M-P1a from
> IMPLEMENTATION_PLAYBOOK.md — exactly as specified: 7 deterministic trigger
> scanners in a NEW learn_agent/coach_service.py, thin /api/coach +
> accept/dismiss routes, and REPLACE Mission Control's 3-rule proto-coach
> (it is labeled as superseded — see D16). Write the trigger unit tests with
> synthetic memory fixtures BEFORE the triggers; every recommendation must
> cite file/concept/corpus evidence. Human decision H1 is approved: [HUMAN:
> confirm/adjust]. Persistence choice must coordinate with H4 status:
> [HUMAN: state H4 decision or "undecided — use aios.db recommendations
> table, DROP-safe"]. Respect PROJECT_CHARTER.md P1–P10; finish with the
> full §V Validation Checklist (12 suites), memory updates per Definition of
> Done, and evidence, not adjectives. Do not begin WP‑4 in this session.

## Prompt B — WP‑4 (M-P2a Teacher skill — the migration core)

> Read START_HERE.md at ~/Desktop/Agentic AI and complete its boot sequence.
> Then execute WP‑4 of MIGRATION_EXECUTION_PLAN.md — milestone M-P2a:
> convert the legacy tutor into brain/skills/teacher/, an agent-type skill
> with the full 11-file profile (templates/skill/, SKILL_AUTHOR_GUIDE.md);
> it must be VALID under `python3 -m aios_core.skill_sdk.validator
> brain/skills/teacher full` with quality ≥85 before registration (D17).
> Reframe learn_agent/agent.py as the ADAPTER only: LLM client, no
> retrieval, no session dict — lesson retrieval goes through the Retrieval
> Gateway with mission scope (P9), and completing a lesson upserts a concept
> with {corpus, source} provenance which the critic then scores (P3, P7).
> The output schema includes concept fields + exercise; outputs failing it
> are rejected — never loosen the schema. Prerequisites confirmed by the
> human: WP‑1 merged and green; H5 decided as [HUMAN: exercise | retire
> distill.py DeepSeek path]. Keep legacy /ask working until exit criteria
> pass (architecture §7: old product keeps working at every step). Write the
> contract tests in brain/tests/test_library_skills.py BEFORE wiring the
> route (NOT_EXECUTABLE without adapter + a schema-reject negative; suite
> must pass with a stub adapter, no API keys). Finish with the §V checklist,
> memory updates per Definition of Done (decisions.md entry ONLY if an
> irreversible choice was made), and evidence, not adjectives. Do not start
> WP‑5 in this session.

---

## Session-exit contract (both prompts)

The session is done when it reports, in this order:
1. §V — 12/12 suites `ALL PASS` (paste the tails).
2. The WP's exit criteria from MIGRATION_EXECUTION_PLAN.md, each with the
   file/output that proves it.
3. Memory delta: the one log.md line added; state.md rows changed; any
   decisions.md entry.
4. Anything discovered that belongs in "Remaining human decisions" — appended
   to HANDOFF.md, never guessed at (Claude_Opus.md known-limitation rule).
