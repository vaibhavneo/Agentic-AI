# Evaluation contract — __SKILL_ID__

Charter P6: build the eval FIRST; external ground truth beats self-consistency.

## MUST checks (deterministic; tests/ implements each)
- **E1 — __name__**: __check + the ground truth it compares against (book value,
  hand arithmetic, classical table, fixed fixture)__
- **E2 — negative control**: __gibberish/empty/adversarial input ⇒ honest
  empty/typed failure — never fabricated output__
- **E3 — bounds/dimensional sanity**: __every numeric output has a stated valid
  range, asserted (LESSONS L4)__

## Quality checks (scored, optional)
- __…__

## Discrimination statement (mandatory)
__Name one plausible wrong implementation each MUST check would catch. An eval
everything passes tests nothing.__
