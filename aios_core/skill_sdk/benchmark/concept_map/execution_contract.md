# Execution contract — concept_map (recreation)
1. **LOAD_STORE** — pre: none; post: concepts dict (empty if file absent).
2. **FILTER** — pre: concepts loaded; post: keep-set honoring min_confidence + name_contains.
3. **BUILD_GRAPH** — pre: keep-set; post: nodes+edges, both-endpoints invariant enforced.
## Failure handling
| condition | behavior | surfaced as |
|---|---|---|
| store file absent | empty graph (documented precondition) | ok:true, n=0 |
| store unparseable JSON | raise | EXECUTION_ERROR |
| unknown input field | rejected by schema | INPUT_INVALID |
Retries: 0 (fully deterministic).
## Metrics
runtime-standard; watch n and len(edges).
