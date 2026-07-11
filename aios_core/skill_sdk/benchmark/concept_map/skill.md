# concept_map (recreation) — behavioral contract
## Purpose
Turn the flat verified concept store into a navigable graph.
## Business problem
Concepts + relationships exist as flat JSON; exploring "what connects to what" requires a graph view, not a list.
## Inputs
`min_confidence` (float, default 0) — exclusive floor is NOT implied; nodes with confidence >= floor survive. `name_contains` — case-insensitive substring on the concept name. `store_path` — test seam (defaults to memory/concepts.json).
## Outputs
`nodes[{name, confidence, status}]`, `edges[{from,to,type}]`, `n=len(nodes)`. Invariant: every edge's endpoints appear in nodes (no dangling edges).
## Determinism
Deterministic: same store+inputs => identical output. Ordering: nodes sorted by name, edges by source name (contract gap G1 — original left ordering unspecified).
## Hidden-assumption audit
Assumes concepts.json schema {concepts:{name:{confidence, verification.status, relationships[{to,type}]}}}; absent/empty store => empty graph (checked, not raised); path resolved from repo root, not cwd.
## Preconditions / Postconditions
Pre: none hard (store optional). Post: no dangling edges; n == len(nodes).
