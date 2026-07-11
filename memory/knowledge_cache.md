# knowledge_cache.md — Distilled Mental Models (RENDERED VIEW)
<!-- SOURCE OF TRUTH: memory/concepts.json — edit via concept_store.py, not here. -->

## Pattern Decomposition (Gullí)
**Confidence:** 1.00 (supported)
**Principle:** Any agent behavior decomposes into a small catalog of reusable patterns (ReAct, reflection, planning, routing, multi-agent coordination) — build from the catalog, don't invent bespoke loops.
**When to use:** Designing any new agent: first ask "which of the 21 patterns is this?", only write custom orchestration when none fits.
**Sources:** curated-wiki:agentic-ai/agentic-design-patterns.md
**Related:** complements → Framework-Last Selection

## RAG Maturity Ladder
**Confidence:** 1.00 (supported)
**Principle:** RAG is not one technique but a ladder — naive keyword → vector search → modular retrieval components → GraphRAG/MAS-RAG — and each rung has a cost; climb only when the current rung measurably fails.
**When to use:** Whenever retrieval quality is questioned: identify the current rung and the specific failure before upgrading (e.g., TF-IDF → embeddings only if keyword recall is the proven bottleneck).
**Sources:** curated-wiki:generative-ai/rag-driven-generative-ai.md
**Related:** depends-on → Evaluator as First-Class Role

## Memory ≠ One Thing
**Confidence:** 1.00 (supported)
**Principle:** Agent memory splits into distinct types (short-term/context, long-term episodic, semantic, shared blackboard) with different write policies — conflating them causes both context bloat and forgetting.
**When to use:** When an agent "forgets" or its context overflows: diagnose which memory type is missing/overloaded rather than just enlarging the prompt.
**Sources:** curated-wiki:agentic-ai/illustrated-guide-to-ai-agents.md
**Related:** complements → Context Engineering Over Prompt Tweaking

## Context Engineering Over Prompt Tweaking
**Confidence:** 1.00 (supported)
**Principle:** What's *inside* the context window (selection, compression, structure — context-as-specification) determines output quality more than wording tricks; optimize the payload, not the phrasing.
**When to use:** Before rewording any underperforming prompt: audit what facts the model actually receives (the Jyoti lordship bug — hallucination from missing data, not bad wording — is the canonical local example).
**Sources:** curated-wiki:agentic-ai/illustrated-guide-to-ai-agents.md, curated-wiki:generative-ai/prompt-engineering-for-llms.md
**Related:** complements → Grounding Beats Generation

## Document-Completion Frame (Berryman)
**Confidence:** 1.00 (supported)
**Principle:** An LLM is a document completer seeing tokens, not letters or intent — hallucinations, repetition traps, and format drift are all consequences; design prompts as documents whose most-likely continuation is the answer you want.
**When to use:** Debugging any weird LLM output (markdown fences, truncation, made-up fields): ask "what document does the model think it's completing?"
**Sources:** curated-wiki:generative-ai/prompt-engineering-for-llms.md
**Related:** explains → Context Engineering Over Prompt Tweaking

## Tool Lifecycle Discipline
**Confidence:** 1.00 (supported)
**Principle:** Tools follow a lifecycle — create → define (schema) → select → call → process output — and most tool failures are at the *definition* and *output-processing* ends, not the call itself.
**When to use:** When an agent misuses tools: tighten schemas/descriptions and post-process outputs before touching the agent's reasoning loop.
**Sources:** curated-wiki:agentic-ai/illustrated-guide-to-ai-agents.md, curated-wiki:agentic-ai/agentic-design-patterns.md
**Related:** instance-of → Pattern Decomposition (Gullí)

## Escalating Autonomy (L0→L5)
**Confidence:** 1.00 (supported)
**Principle:** Agent autonomy is a graded ladder (chatbot → tool-user → planner → multi-agent → self-improving); each level adds failure modes, so grant the *lowest* level that achieves the task.
**When to use:** Scoping any new agent: pick the level deliberately, and require evidence (eval results) before promoting a system up a level.
**Sources:** curated-wiki:agentic-ai/ai-agents-and-applications.md, workspace:reference_30_agents_catalog (persistent memory)
**Related:** depends-on → Evaluator as First-Class Role
**Flags:** non-index provenance (cannot verify by retrieval): workspace:reference_30_agents_catalog (persistent memory)

## Grounding Beats Generation
**Confidence:** 0.28 (unsupported)
**Principle:** Never let an LLM invent numbers or facts a deterministic computation can supply — compute the fact, hand it to the model as ground truth, and instruct it to cite, not derive.
**When to use:** Any pipeline where LLM output includes verifiable claims (prices, placements, dates): add a computed-facts block first (stock_agent grounding + vedic house-lords table are the local proofs).
**Sources:** curated-wiki:agentic-ai/ai-engineering.md, workspace:workspace-validation (stock_agent grounding, vedic house-lords)
**Related:** complements → Evaluator as First-Class Role
**Flags:** claimed source not in top-5 evidence: curated-wiki:agentic-ai/ai-engineering.md; non-index provenance (cannot verify by retrieval): workspace:workspace-validation (stock_agent grounding, vedic house-lords)

## Evaluator as First-Class Role
**Confidence:** 1.00 (supported)
**Principle:** A generation system has four roles — Retriever, Generator, Evaluator, Trainer — and skipping the Evaluator means quality claims are anecdotes; build the eval before trusting the output.
**When to use:** Before shipping any LLM feature: define the ground-truth check first (the 12-ascendant lordship eval and backtest leak-test pattern).
**Sources:** curated-wiki:generative-ai/rag-driven-generative-ai.md

## Framework-Last Selection
**Confidence:** 0.81 (supported)
**Principle:** Choose orchestration frameworks (LangGraph, CrewAI, AutoGen, raw SDK) by the coordination topology the task needs — not by popularity; simple sequential/parallel flows rarely justify a framework at all.
**When to use:** At project start: sketch the agent topology on paper first; adopt a framework only when the topology (cycles, handoffs, shared state) demands it.
**Sources:** curated-wiki:agentic-ai/ai-agents-and-applications.md, workspace:reference_agent_protocols_frameworks (persistent memory)
**Flags:** non-index provenance (cannot verify by retrieval): workspace:reference_agent_protocols_frameworks (persistent memory)
