# AI Engineering Pack

The reference Domain Pack for building agentic AI systems. Its corpora
(ai-books, curated-wiki, llm-books) and mental models already power the
platform itself, which makes it the canonical example of the pack contract.

- **Skills:** `concept_map` (new, deterministic) + composes core skills.
- **Workflows:** `ai_engineering_research` (retrieve → concept_map).
- **Mission templates:** build-agent-system, learn-multi-agent-systems.
- **Corpora:** reuses existing ai-books / curated-wiki / llm-books.
- **Loads via:** `packs/loader.py` (PackManager) — zero AIOS Core changes.

Run its tests: `python3 packs/ai_engineering/tests/test_pack.py`
Full architecture: `DOMAIN_PACKS.md`.
