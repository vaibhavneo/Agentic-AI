# critic_report.md — Evidence Verification
<!-- Generated 2026-07-10 by second_brain/critic.py. Overwritten each run. -->

| concept | confidence | status | flags |
|---|---|---|---|
| Pattern Decomposition (Gullí) | 1.00 | supported | 0 |
| RAG Maturity Ladder | 1.00 | supported | 0 |
| Memory ≠ One Thing | 1.00 | supported | 0 |
| Context Engineering Over Prompt Tweaking | 1.00 | supported | 0 |
| Document-Completion Frame (Berryman) | 1.00 | supported | 0 |
| Tool Lifecycle Discipline | 1.00 | supported | 0 |
| Escalating Autonomy (L0→L5) | 1.00 | supported | 1 |
| Evaluator as First-Class Role | 1.00 | supported | 0 |
| Framework-Last Selection | 0.81 | supported | 1 |
| Grounding Beats Generation | 0.28 | unsupported | 2 |

## Flag detail
- **Escalating Autonomy (L0→L5)**: non-index provenance (cannot verify by retrieval): workspace:reference_30_agents_catalog (persistent memory)
- **Grounding Beats Generation**: claimed source not in top-5 evidence: curated-wiki:agentic-ai/ai-engineering.md
- **Grounding Beats Generation**: non-index provenance (cannot verify by retrieval): workspace:workspace-validation (stock_agent grounding, vedic house-lords)
- **Framework-Last Selection**: non-index provenance (cannot verify by retrieval): workspace:reference_agent_protocols_frameworks (persistent memory)

Method: confidence = 0.5·retrieval_support + 0.5·source_corroboration (deterministic; see critic.py docstring). 'partial' usually means the principle generalizes beyond what the small curated index can confirm — a signal to ingest more sources, not necessarily a wrong claim.