# Skill: concept_map v1.0.0 (AI Engineering Pack)

**Purpose:** turn the flat verified concept store into a navigable graph.

**Inputs:** `min_confidence` (float, default 0.0) · `name_contains` (str, optional filter).
**Outputs:** `{nodes: [{name, confidence, status}], edges: [{from, to, type}], n}`.
**Execution:** LOAD_STORE (memory/concepts.json) → FILTER → BUILD_GRAPH. Deterministic; no dangling edges (both endpoints must survive the filter).
**Preconditions:** concepts.json exists (empty store → empty graph, not an error).
**Postconditions:** every returned edge connects two returned nodes.
**Failure modes:** INPUT_INVALID (unknown field), runtime errors surfaced as EXECUTION_ERROR.
**Memory:** stateless (root_param null) — read-only over the concept store.
**Dependencies:** none. **Success metric:** graph matches concepts.json by hand for a fixed filter.
