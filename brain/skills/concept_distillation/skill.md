---
name: concept_distillation
version: 1.0.0
description: Compress retrieved knowledge into reusable mental models (name + principle + when-to-use + sources). Use when converting ingested material into decision-making tools.
reference_impl: memory/concepts.json (10 models, cycle 1); legacy second_brain/distill.py retired D19
---
# concept_distillation
**Purpose:** knowledge that transfers — a model you can apply without re-reading the book.
**Inputs:** `topic` (str) · retrieval index · existing concept store (for dedup)
**Outputs:** concept record {name, principle (1 sentence), when_to_use (1 sentence), sources[]} upserted into concepts.json; NEVER appended to the rendered markdown view directly.
**Contract:** distill FROM retrieved chunks (retrieve_context first — priors alone are not a source) · dedup by name · every concept enters as `unverified` until evidence_validation runs · principle must be falsifiable, when_to_use must name a trigger situation.
**Downstream:** evidence_validation assigns confidence; concept_store links relationships.
