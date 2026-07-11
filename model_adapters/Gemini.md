# Adapter — Gemini

**Interpretation**: same as GPT.md — repository contracts are model-neutral.
Boot via START_HERE.md; effort profile: atomic tasks first.

**Watch for**: long-context strengths tempt whole-repo rewrites — the charter
forbids regeneration where refinement works (P-philosophy: refinement over
regeneration; rewrites require a decisions.md entry). Keep diffs minimal.
**Recommended tasks**: corpus ingestion + retrieval-quality evaluation (M-K)
is a good first assignment: measurable, low blast radius, exercises the
gateway contract end to end.
**Prompting convention**: same as GPT.md; additionally pin the working
directory explicitly in every session (multiple apps live in this repo —
stock_agent/vedic_astro have their OWN conventions in their CLAUDE.md files;
do not cross-apply them to AIOS code).
**Known limitation**: if your tooling cannot run local test scripts, do not
mark anything done — the Definition of Done requires executed checks; produce
the code and explicitly hand validation back to the human.
