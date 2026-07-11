# plan.md — Execution Plan
<!-- Max depth 3. Atomic steps. Check off + prune completed phases; do not append history. -->

## Objective
Second Brain MVP: ingest → retrieve → distill → cache → recursive loop until stable.

## Cycle 1 — COMPLETE (all phases done; details pruned per no-history rule, see log.md)
- [x] Phase 1 Ingest · [x] Phase 2 Retrieve · [x] Phase 3 Distill (10 models) · [x] Phase 4 Loop → STABLE

## Cycle 3 — Engine hardening — COMPLETE
- [x] 3A Validation suite: 20 tests / 5 stages → validation_report.md (20/20)
- [x] 3B Critic Agent: deterministic evidence verification → critic_report.md (9 supported / 1 honestly-unsupported)
- [x] 3C Structured concept memory: concepts.json (source of truth) + 8 typed edges; knowledge_cache.md now a rendered view

## Cycle 4 — Candidates (pick ONE when resumed)
- [ ] 4A Ingest raw/library/ (456 books) — primary lever to raise the unsupported concept's confidence (per D11)
- [x] 4B DROPPED (D19): distill.py retired, not live-tested — distillation is the concept_distillation skill; new distills route through it (RETRIEVE→...→UPSERT) + critic
- [ ] 4C Grow store toward 25 concepts (fine-tuning vs RAG, HiTL, AgentOps, GraphRAG, safety)

## Next Action
→ Choose M-P1a (coach triggers) or M-Q1 (platform quality — self-analysis
findings, PLATFORM_IMPROVEMENT_REPORT.md) per IMPLEMENTATION_PLAYBOOK.md —
both await approval to start. Boot any new session via START_HERE.md.

## M-Q1 — Platform Quality (self-analysis, 2026-07-06) — QUEUED (Q1g CLOSED by C16.1)
- Full findings + rationale: PLATFORM_IMPROVEMENT_REPORT.md
- Sub-items Q1a–Q1j in IMPLEMENTATION_PLAYBOOK.md, priority-ordered
- Top 2 (critical): Q1a docs staleness (START_HERE/HANDBOOK missing
  aios_core/packs/Mission Control), Q1b metrics.jsonl retention+correctness

## AIOS (learn_agent → Personal AI OS) — DESIGN APPROVED (v1.1: Corpus Manager amendment)
- Architecture: learn_agent/AIOS_ARCHITECTURE.md (v1.1, §6.5 Corpus Manager + Retrieval Gateway)
- [x] P0.1 Corpus Manager (registry.json + book_ingestion v1.1 + seed 3 corpora from existing indexes)
- [x] P0.2 Retrieval Gateway (retrieve(query, mission); normalize/dedup/confidence/provenance; unit tests first)
- [x] P0.3 Mission model (requires ≥1 corpus; mission_corpora mapping; seed 2 missions)
- [x] P0.4 Shell UI V1/V2 (corpus badges + confidence in context panel)
- [x] P0.5 Command palette + keyboard nav
- [ ] P1 proactive loop (coach triggers; execute mode SSE; task write-path)
- [ ] P2 learning system (learn mode; retention queue; knowledge graph)
- [ ] P3 depth (architect/code_generator skills; contradictions; memory browser)
