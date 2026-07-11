# __SKILL_ID__ — behavioral contract

## Purpose (mandatory)
__The problem. Why a mission/workflow reaches for this skill. One paragraph max.__

## Business problem (mandatory)
__Who is blocked without it and what they do instead (the manual/broken alternative).__

## Inputs (mandatory)
__Prose meaning of each input field — the schema says types; THIS says semantics,
units, and edge interpretation (empty string vs absent, etc.).__

## Outputs (mandatory)
__Prose meaning of each output field. State invariants the schema can't express
(e.g. "every edge's endpoints appear in nodes").__

## Determinism (mandatory)
__deterministic | agent-gated. If deterministic: same inputs ⇒ byte-equivalent
outputs; name any tolerated nondeterminism (timestamps, ordering) explicitly.
If agent-gated: what the output schema enforces regardless of the adapter.__

## Hidden-assumption audit (mandatory)
__List every assumption about environment/files/state (paths that must exist,
index formats, cwd). Each must be either checked at runtime (→ failure mode)
or declared as a precondition here. "None" is a valid answer only after checking.__

## Preconditions / Postconditions (mandatory)
- Pre: __…__
- Post: __…__

## When NOT to use (optional but recommended)
__The neighboring skill someone probably wants instead.__
