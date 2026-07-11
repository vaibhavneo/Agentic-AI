# Skill: teacher v1.0.0

**Purpose:** Turning a knowledge base into learning requires instruction that adapts to what a learner already knows and cites where every claim comes from; a raw chatbot answer does neither and cannot be verified or resumed.

**What it does:** Adaptive, source-grounded instruction — retrieve scoped evidence, assess mastery + prerequisites deterministically, delegate the explanation/exercise/mastery-check to an adapter, and emit a structured lesson with provenance.

| aspect | value |
|---|---|
| runtime | python driver `aios_core.runtime.drivers.teacher_driver:run` — **adapter-gated** (`context["agent_adapter"]` required; `NOT_EXECUTABLE` otherwise) |
| execution steps | RESOLVE SCOPE → RETRIEVE EVIDENCE → ASSESS MASTERY → INSTRUCT → ASSEMBLE LESSON |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | stateless (root_param `null`; no reads/writes of a memory root; zero `memory_changes`) |
| dependencies | `retrieve_context` `>=1.0.0 <3.0.0` (required) |
| failure modes | `NOT_EXECUTABLE` (no adapter); `EXECUTION_ERROR` (no scope / retrieval failure / adapter missing keys) |
| success metrics | [evaluation_contract.md](evaluation_contract.md) E1–E5 |
| version | 1.0.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | any executor honoring the runtime contracts (charter P8); core `>=1.0.0 <2.0.0` |

**Adaptive on:** concept confidence, prerequisite gaps, prior activity, mission
context (scope), and retrieved sources. **Distinguished output parts:**
explanation · source evidence · learner exercise · mastery check · recommended
next action. **Downstream loop (M-P2a):** the caller routes `concept_candidate`
→ `concept_store.upsert` → `evidence_validation` (critic) — the skill itself
writes nothing.

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
