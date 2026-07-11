# SKILL AUTHOR GUIDE — how to write an AIOS skill

Audience: any model (or human) authoring a skill with zero conversation
history. Prerequisites: PROJECT_CHARTER.md (P1–P10), SKILL_SDK.md (structure),
SKILL_RUNTIME_SPEC.md (runtime contract). Reference implementation to copy:
`brain/skills/recursive_planner/` — **the flagship is the worked example for
every convention in this guide.**

---

## 1. Identify a reusable capability (or decline to)

A capability deserves to be a skill when ALL hold:
1. **Named need** — a mission/workflow reaches for it more than once, or two
   apps would otherwise implement it separately (that duplication test is how
   `workflow.BackgroundRun` and the library drivers were born).
2. **Contractable** — you can state inputs/outputs as schemas and completion
   as a deterministic check. If "done" is a judgment call, it's an agent-type
   skill whose OUTPUT is still schema-contractable — or it's not a skill yet.
3. **Right altitude** — one atomic responsibility (P5). "Analyze a stock" is
   a workflow; "run one backtest" is a skill. If your steps list reads like a
   pipeline of independently useful stages, you're holding several skills.

Decline when: it's used once, in one app (leave it as app code until the
second consumer appears — YAGNI, LESSONS §2); or it's pure presentation (P10:
UI stays thin, never a skill).

## 2. Decompose complex tasks

Work backwards from the evaluation: write the deterministic check that would
prove the whole task done, then split at every point where a HUMAN could hand
the work to someone else with only a document. Each hand-off document = one
skill contract. Depth limit: if a skill needs its own internal multi-phase
plan, it's a workflow of smaller skills (max plan depth 3 — D7). Deterministic
sub-steps become python drivers; judgment sub-steps become agent-type skills
gated by output schemas; NEVER blend both in one driver (the critic/grounding
split exists precisely because generation and verification must not share a
brain — D10).

## 3. Define contracts (in this order)

1. **evaluation_contract.md first** (P6). Find external ground truth: a book
   value, hand arithmetic, a classical table, a synthetic fixture with a
   scripted answer. Write the discrimination statement — if you can't name a
   wrong implementation your check would catch, the check is decoration.
2. **Schemas second.** `additionalProperties: false` on inputs (catches
   caller typos as INPUT_INVALID instead of silent ignoring). Every numeric
   output gets a stated range, asserted in tests (LESSONS L4: a 3,200%
   drawdown shipped because nobody asked "can this exceed 1.0?").
3. **skill.md + execution_contract.md third.** Steps with pre/post; failure
   table with the EXACT behavior per condition (empty-result vs raise —
   choose and justify; retrieval returns honest-empty for gibberish, loaders
   raise for missing sources — both are right, in context).
4. **Driver last.** By the time you write code, the code is transcription.

## 4. Design deterministic skills

- Same inputs ⇒ byte-equivalent outputs. Sort everything you iterate
  (dict order, glob order); never embed timestamps in outputs (metrics carry
  time); tolerate zero RNG without a seeded parameter.
- Compute, don't generate (P4): if a number can come from a formula, the LLM
  never supplies it. Twice-proven pattern: compute the fact table, hand it to
  any generative step as ground truth, instruct "cite, don't derive."
- Edge-case floors: empty store → empty result (not error); single-item
  corpus → still retrievable (LESSONS L3 — the smoothed-idf bug only surfaced
  through a 1-file synthetic fixture; ALWAYS test the degenerate size).

## 5. Avoid hidden assumptions

The `skill.md` **Hidden-assumption audit** section is mandatory because these
five have each caused a real bug here:
- **Paths**: never assume cwd; resolve from `Path(__file__)` (drivers) or
  take roots as inputs. Declare every file the skill expects to exist.
- **Module identity**: import via the exact path the executor uses
  (`aios_core.runtime.drivers.X`) — two import paths = two module objects =
  state armed in one is invisible in the other (LESSONS L7).
- **Environment**: Python 3.9 floor — no `X | None` in FastAPI-visible
  signatures (L8); no deps beyond stdlib without charter-level justification.
- **Scale**: state the tested corpus/file size envelope. "Works" at 96 chunks
  is a claim about 96 chunks (see LESSONS §3 ai-books note).
- **Freshness**: if the skill reads a rebuildable index/view, say what happens
  when it's stale or absent.

## 6. Write examples

Examples are executable documentation — the validator (V6) requires ≥1 happy
path and ≥1 negative, and your tests must REPLAY them (drift between examples
and behavior is a test failure, not a docs chore). A good happy-path example
is boring and representative; a good negative example encodes the failure
TABLE's promise (gibberish → honest empty; missing precondition → typed
error). If an example needs three paragraphs of notes, the contract is
under-specified — fix skill.md instead.

## 7. Write regression tests

House rules (charter §7 + proven incidents):
- Standalone scripts: `python3 tests/test_x.py`, exit 1 on failure, print
  `ALL PASS`, evidence next to every verdict.
- **Idempotent**: create and destroy your own scratch state; never depend on
  a previous run's leftovers (two real incidents: L7).
- One test per evaluation MUST + example replay + ≥1 negative path + bounds
  checks on every numeric output.
- Prefer external ground truth over self-consistency; synthetic fixtures with
  scripted answers beat realistic data that hides bugs (the leak test and the
  1-chunk corpus both caught real defects realistic data missed).
- A test everything passes tests nothing — include one assertion that a
  plausible wrong implementation would fail (discrimination).

## 8. Version skills

Semver, enforced by validator V9 (CHANGELOG top entry == manifest.version):
- **MAJOR** — input/output schema field type or requiredness changes; memory
  contract loosening (new write paths); execution step reorder/removal;
  behavior change to an existing contract promise.
- **MINOR** — new optional input (with default); additional output field;
  new example/test; tightened (never loosened) validation.
- **PATCH** — docs, typos, test-only changes, internal refactor with
  byte-identical behavior.
Registry constraints pin majors (`>=1.0.0 <2.0.0`); the runtime fails loudly
on incompatibility rather than best-effort matching. Never republish a
version; never edit a released CHANGELOG entry.

## 9. Engineering rules (Part 9 — knowledge preserved from Phases 1–5)

Each rule earned its place through a documented incident (full stories:
LESSONS.md; decisions: memory/decisions.md):

| # | rule | provenance |
|---|---|---|
| R1 | Compute facts; LLMs cite, never derive | L1 (invented prices, invented house lords) |
| R2 | Fix the payload before the phrasing | L2 (truncated context, not bad prompt) |
| R3 | Test the degenerate size (0, 1, huge) | L3 (negative idf on 1-chunk corpus) |
| R4 | Every metric declares its valid range; tests assert it | L4 (MaxDD 32×) |
| R5 | Corroboration must be credible, not merely aligned | L5 (losing strategy "confirming" a BUY) |
| R6 | Scores from different populations need normalization before comparison | L6 |
| R7 | Tests own their state; import via the executor's module path | L7 |
| R8 | Python 3.9: `Optional[X]`, not `X \| None`, in runtime-evaluated signatures | L8 |
| R9 | Generator and grader never share a brain | D10 |
| R10 | Unsupported stays flagged; acquire evidence, never edit verdicts | D11/P7 |
| R11 | Scope is never guessed; no default corpus | P9 (v1.1 amendment) |
| R12 | Files are truth; DBs/views are rebuildable; write-only mirrors are debt | P2 + improvement-report P8 |
| R13 | Adopt existing indexes/formats where compatible; verify format FIRST | L10 |
| R14 | One machine format (JSON) per artifact class; no YAML twins | D13 |
| R15 | Thin surfaces: routes/UI wrap SDK calls, zero business logic | P10 (verified by source-level tests) |
| R16 | Known limits get a decision (fix or retire) within a few cycles — undecided ages into forgotten | improvement-report P9 (15-cycle stall) |
| R17 | Test fixtures stay out of production registries and telemetry | improvement-report P2/P3 |
| R18 | Docs enumerating N things must be validated against the N things (drift check) | improvement-report P1/P7 (repeat finding) |
