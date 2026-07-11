# Skill: concept_map v1.0.0 (SDK BENCHMARK RECREATION — not registered)
**Purpose:** turn the flat verified concept store into a navigable graph.
**What it does:** nodes+typed edges from memory/concepts.json, filtered, no dangling edges.
| aspect | value |
|---|---|
| runtime | python → `aios_core.skill_sdk.benchmark.concept_map.driver:run` |
| execution steps | LOAD_STORE → FILTER → BUILD_GRAPH |
| memory | stateless, read-only |
| dependencies | none |
| version | 1.0.0 — see CHANGELOG.md |
Recreation provenance + comparison vs original: BENCHMARK_REPORT.md.
