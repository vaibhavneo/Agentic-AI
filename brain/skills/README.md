# Brain Skill Library — v1.0.0

Model-agnostic cognitive skills extracted from working implementations in this
workspace. Each skill defines WHAT must happen (contracts + schemas), never
WHICH model performs it. `recursive_planner` is the fully-packaged flagship
(schemas, contracts, evaluation, examples, tests); the other nine are contract
cards following the same conventions and cite their reference implementation.

## Skills
| skill | one-line role | reference impl |
|---|---|---|
| recursive_planner | file-persistent goal loop (flagship, full package) | second_brain/ + memory/ |
| book_ingestion | corpus → chunked retrievable index | second_brain/ingest.py |
| retrieve_context | bounded, cited retrieval before reasoning | second_brain/retrieve.py |
| rag_search | ingest→retrieve→ground→cite answering | vedic_astro KB |
| concept_distillation | retrieved knowledge → reusable mental models | memory/concepts.json (agent-type; distill.py retired D19) |
| hypothesis_generation | falsifiable proposals with kill tests | stock_agent strategies |
| evidence_validation | claims → calibrated confidence + flags | second_brain/critic.py |
| critic | adversarial post-generation review | critic.py, positive-edge filter |
| evaluator | deterministic checks before trust | test_pipeline.py, book-truth tests |
| memory_compression | durable summaries, bounded files | memory/ discipline |

## Composition rule
Skills chain by contract, not by prompt: each skill's Outputs section must
satisfy the next skill's Inputs. Canonical chains live in ../workflows/.

## Live memory mapping (this workspace)
The loop's live memory (per decision D1) is at repo root `memory/` — brain/memory/
is the orchestrator's code, not the loop state.
