# DOMAIN PACKS — reusable knowledge domains on AIOS Core

Read `PROJECT_CHARTER.md` and `AIOS_HANDBOOK.md` first. A **Domain Pack** is a
self-contained folder that adds skills, workflows, corpora, mission templates,
evaluation rules and memory extensions for ONE knowledge domain — **without
modifying AIOS Core**. Packs plug in only through documented core interfaces.
Version 1.0.0.

Proven working: `packs/ai_engineering/` loads and dispatches a new skill
through the completely unmodified core (`python3 packs/tests/test_domain_packs.py`
→ ALL PASS).

---

## 1. Why packs, and the one rule

The platform must support independent domains (AI engineering, product,
finance, astrology, …) that evolve on their own cadence. AIOS Core is the
engine; a Domain Pack is *content + capability* for one domain. The rule:

> A pack extends the core only through: the composite **Registry** (skills),
> `retrieval.register_corpus` (corpora), the **Mission** SDK (templates), and
> `workflow.run(..., registry=)` (workflows). **No core file is edited.**

This is enforceable and enforced — `PackManager.load()` builds an in-memory
composite registry and never writes to `brain/skills/registry.json`; a test
asserts the core registry is byte-identical before and after a load.

## 2. The pack contract (folder structure)

```
packs/
  loader.py                     # PackManager — the ONLY new infrastructure (uses core SDK)
  tests/test_domain_packs.py    # cross-pack regression
  <pack_id>/
    pack.json                   # the descriptor (see §3) — JSON, not YAML*
    corpora.json                # knowledge-source notes / declarations
    skills/<id>/manifest.json   # pack skills (inline-registered; standard 12-field manifest)
    skills/<id>/skill.md        # behavioral contract
    drivers/*.py                # deterministic skill drivers (importable module paths)
    workflows/*.workflow.json   # domain workflows (skills-only, $step.field binding)
    mission_templates: in pack.json (or a file)   # presets: title/type/goal/corpora/tasks
    evaluation.md               # domain eval rules + ground truth (P6)
    memory/                     # pack-scoped memory namespace (notes, insights)
    tests/test_pack.py          # pack-local checks
    README.md
```

\* **pack.json, not pack.yaml** — deliberate, per decision D13 (one machine
format, stdlib `json`, no new dependency). Same reasoning that made skill
manifests `manifest.json` not `skill.yaml`. Content is identical to what a
YAML file would hold.

## 3. The descriptor (`pack.json`)

```jsonc
{
  "id": "ai_engineering",
  "name": "AI Engineering Pack",
  "version": "1.0.0",                    // semver
  "description": "...",
  "domain": "ai-engineering",
  "aios_core_compat": ">=1.0.0 <2.0.0",  // which core majors this pack supports
  "corpora": ["ai-books", "curated-wiki"],       // corpus ids USED (must resolve)
  "provides_corpora": [],                         // NEW inline corpora this pack registers
  "skills": [{"manifest_path": "skills/concept_map/manifest.json"}],
  "workflows": ["domain_research.workflow.json"],
  "mission_templates": [ {"id","title","type","goal","corpora","cross_corpus","tasks"} ],
  "memory_namespace": "packs/ai_engineering",
  "retrieval": {"default_corpora": ["ai-books","curated-wiki"], "cross_corpus": false},
  "evaluation": "evaluation.md"
}
```

## 4. The loader interface (`packs/loader.py`, `PackManager`)

| method | does |
|---|---|
| `discover()` | pack ids under `packs/` |
| `load(pack_id, ingest_corpora=False)` | merge pack skills into the composite registry; register any `provides_corpora` (idempotent) |
| `load_all()` | load every discovered pack |
| `registry()` | the composite `Registry` (core skills + all loaded pack skills) |
| `run_skill(id, inputs, ctx)` | `dispatch(..., registry=composite)` — pack OR core skill, through the unmodified core |
| `run_workflow(wf, ctx)` | core `run_workflow(..., registry=composite)` |
| `mission_templates(pack_id=None)` | pack-namespaced template dict (`pack:template_id`) |
| `instantiate_template(key, store)` | create a real mission via the Mission SDK |
| `conformance(pack_id)` | deterministic pack-contract validator (§8) |

Only documented core surfaces are touched: `dispatch`/`run_workflow` already
accept a `registry=` (runtime extension point #4 "Registry sources"),
`retrieval.register_corpus`, and the Mission SDK.

## 5. The four packs

Each spec below is uniform. The **AI Engineering** pack is fully implemented as
the reference; the other three are specified for implementation and map onto
capability that already exists in `stock_agent/`, `vedic_astro/`, and
(new) product tooling.

### 5.1 AI Engineering Pack — `packs/ai_engineering/` (IMPLEMENTED)

- **Folder:** as §2. **Version:** 1.0.0, compat `>=1.0.0 <2.0.0`.
- **Skills:** `concept_map` (new, deterministic — concept sub-graph from
  concepts.json); composes core `retrieve_context`, `evidence_validation`,
  `evaluator`. Future: `architect`, `code_generator` (agent-type, playbook M-P3).
- **Workflows:** `ai_engineering_research` (retrieve → concept_map). Future:
  W-architecture, W-coding recipes from `brain/workflows/WORKFLOWS.md`.
- **Knowledge sources:** corpora `ai-books` (25,812 chunks), `curated-wiki`
  (96), `llm-books`. Reuse-only (`provides_corpora: []`).
- **Evaluation:** concept_map integrity (no dangling edges), retrieval scope
  honored, pack conformance. Ground truth = the 10 critic-verified concepts.
- **Mission templates:** build-agent-system, learn-multi-agent-systems.
- **Memory extensions:** `packs/ai_engineering/memory/` namespace for domain
  notes/insights (kept out of global `memory/`).
- **Retrieval config:** default corpora `[ai-books, curated-wiki]`, cross_corpus off.
- **Tests:** `tests/test_pack.py` + cross-pack `packs/tests/test_domain_packs.py`.
- **Versioning:** semver; breaking = removing a skill/template or narrowing a
  skill schema; compatible = new skills/templates/corpora.

### 5.2 Product Management Pack — `packs/product_management/` (SPEC)

- **Skills:** `prd_writer` (agent-type: problem → structured PRD, sections
  enforced by output schema), `roadmap_prioritize` (deterministic: RICE/impact
  score over a backlog file → ranked list), `research_synthesize` (agent-type:
  interview notes → themes ranked by frequency, evidence-cited). All model-
  agnostic (adapters), outputs schema-validated.
- **Workflows:** `discovery` (retrieve market/PM corpus → research_synthesize →
  concept upsert), `spec` (prd_writer → evaluator on acceptance-criteria
  completeness).
- **Knowledge sources:** new corpus `pm-books` (`provides_corpora`, source_dirs
  = PM titles from the library; reliability 0.9); optional `personal-notes`.
- **Evaluation:** PRD MUST contain goals/non-goals/metrics/acceptance-criteria
  (deterministic section check); prioritization is reproducible from the
  backlog file (no LLM in the ranker — P4 grounding).
- **Mission templates:** write-a-prd, quarterly-roadmap, synthesize-user-research.
- **Memory extensions:** `packs/product_management/memory/` (decision log of
  prioritization calls — feeds a future "why did this rank here" audit).
- **Retrieval config:** default `[pm-books]`, cross_corpus off.
- **Tests:** section-completeness check, ranker determinism (same backlog →
  same order), conformance. **Versioning:** semver.

### 5.3 Finance Pack — `packs/finance/` (SPEC; wraps existing stock_agent code)

- **Skills:** `backtest` (deterministic — wraps `stock_agent/backtest/engine.py`
  vectorized backtest + Deflated Sharpe; driver imports the existing engine, no
  reimplementation), `ground_prediction` (deterministic — wraps
  `stock_agent/agents/synthesis.py`: ATR stops, 2:1 targets, Kelly sizing,
  positive-edge filter), `kelly_size` (deterministic). This is P4 grounding as
  a pack: numbers are computed, never LLM-invented.
- **Workflows:** `analyze_ticker` (fetch → backtest across strategies →
  ground_prediction → evidence-cited verdict), `strategy_research`
  (retrieve finance corpus → hypothesis_generation → backtest as the kill test).
- **Knowledge sources:** corpus `finance` (17 PDFs; `provides_corpora` with the
  PDF ingest profile; reliability 0.9 — lossy PDF extraction, per LESSONS).
- **Evaluation:** book-value ground truth (Kelly ≈ 4.5, dSR 3.255≈3.26,
  Hilpisch EUR/USD), MaxDD ∈ [0,1] bounds check, no-look-ahead leak test —
  all already exist in `stock_agent/tests/`; the pack references them.
- **Mission templates:** analyze-a-stock, build-a-trading-strategy,
  research-a-market.
- **Memory extensions:** `packs/finance/memory/` recommendation ledger (the
  existing `stock_agent/data/store.py` recommendations table maps here).
- **Retrieval config:** default `[finance, curated-wiki]`, cross_corpus ON
  (finance is sparse; widening flagged).
- **Tests:** reuse `stock_agent/tests/test_backtest_engine.py` etc. via the
  pack's evaluator; add dispatch tests. **Versioning:** semver.

### 5.4 Astrology Pack — `packs/astrology/` (SPEC; wraps existing vedic_astro code)

- **Skills:** `compute_chart` (deterministic — wraps `vedic_astro/chart/
  calculator.py`, Swiss Ephemeris; birth data → D-1..D-16 + planets),
  `house_lords` (deterministic — wraps the verified house-lordship table;
  the canonical P4 grounding example, all-12-ascendants tested), `divisionals`.
  A generative `interpret` skill (agent-type) is grounded ON these computed
  facts ("cite, don't derive").
- **Workflows:** `chart_reading` (compute_chart → house_lords → interpret with
  computed facts injected), `learn_jyotish` (retrieve astrology corpus →
  teach → concept upsert).
- **Knowledge sources:** corpus `astrology` (23 books; `provides_corpora`;
  reliability 0.9). Classical tables are computed, not retrieved (P4).
- **Evaluation:** the 12-ascendant house-lord ground-truth test (already
  exists, `vedic_astro/tests/test_house_lords.py`), chart placements vs known
  charts (Gandhi demo). Interpretations MUST cite computed placements.
- **Mission templates:** read-a-chart, learn-vedic-astrology.
- **Memory extensions:** `packs/astrology/memory/` per-chart notes.
- **Retrieval config:** default `[astrology]`, cross_corpus off (domain-isolated).
- **Tests:** house-lord ground truth + dispatch tests. **Versioning:** semver.

## 6. Migration plan

The four domains already exist as apps (`brain/skills`, `stock_agent`,
`vedic_astro`, and new PM tooling). Migration is **incremental and
backward-compatible** — no app breaks during the move.

1. **Phase 0 — infrastructure (DONE):** `packs/loader.py` + the AI Engineering
   reference pack + tests. Zero core change; 8 existing suites stay green.
2. **Phase 1 — wrap, don't rewrite:** for finance and astrology, pack skills
   are thin drivers that `import` the existing engines
   (`stock_agent/backtest`, `vedic_astro/chart`). The apps keep working
   unchanged; the pack exposes the same capability through the core dispatcher.
3. **Phase 2 — corpora as packs:** move each domain's corpus declaration into
   its pack's `provides_corpora`; `load(ingest_corpora=True)` populates indexes.
   The shared `memory/corpora/registry.json` remains the store (idempotent).
4. **Phase 3 — templates + workflows:** lift each app's implicit "what you do
   here" into `mission_templates` and `workflows/`.
5. **Phase 4 — apps consume packs:** `learn_agent` / console call
   `PackManager().load_all()` at startup and dispatch via the composite
   registry, so every domain's skills appear in one workspace. For global
   wiring, set `AIOS_SKILLS_DIR` to a generated composite (the documented env
   seam) instead of injecting a registry per call.
6. **Rollback:** delete a pack folder — the apps and core are untouched
   (packs are additive; nothing in core depends on a pack).

**Removal / breaking timeline:** a pack bumps its own major independently of
core. `aios_core_compat` gates it; the loader can refuse a pack whose compat
range excludes the running core version.

## 7. Example implementation

`packs/ai_engineering/` is the worked example — a complete pack that:
- adds a real new deterministic skill (`concept_map`) dispatched through the
  unmodified core,
- ships a workflow composing a core skill + the pack skill,
- exposes two mission templates that instantiate via the Mission SDK,
- reuses existing corpora without polluting the registry,
- passes a conformance check.

Run it: `python3 packs/tests/test_domain_packs.py` → `ALL PASS`.

## 8. Validation strategy

Three layers, all deterministic-first (P6):

1. **Pack conformance (structural)** — `PackManager.conformance(pack_id)`:
   required `pack.json` keys present, semver valid, every skill manifest
   validates (12 fields), workflows reference only known skills, mission
   templates declare corpora (P9), declared corpora resolve, `evaluation.md`
   + `README.md` exist. A pack that fails conformance cannot be trusted to load.
2. **Isolation invariants (the one rule)** — the cross-pack suite asserts:
   loading a pack does NOT mutate `brain/skills/registry.json`; a reuse-only
   pack registers no corpora; the composite registry = core ∪ pack skills;
   core skills still run unchanged via the composite registry.
3. **Domain evaluation (behavioral)** — each pack's `evaluation.md` defines MUST
   checks with external ground truth (finance book values, astrology classical
   tables, PRD section completeness) run through the `evaluator` skill.

**Regression gate (add to the platform checklist):**
```
python3 packs/tests/test_domain_packs.py        # architecture + AI-eng pack
python3 packs/<pack>/tests/test_pack.py          # per pack, as packs are added
```
plus the existing 8 suites (packs must never turn one red — proven for v1.0.0).
