# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Directory Is

A personal workspace combining:
1. **60+ books** on agentic AI, LLMs, multi-agent systems, RAG, and agent frameworks (PDFs/EPUBs at the root)
2. **Four standalone agentic apps**: `brain/`, `health-agent/`, `vedic_astro/`, `stock_agent/` (each has its own conventions; `stock_agent/` and `vedic_astro/` carry their own `CLAUDE.md` — do not cross-apply)
3. **The AIOS platform** — a reusable agent OS (`aios_core/` + `second_brain/` + `brain/skills/` + `learn_agent/` + `packs/`) governed by the docs in §"The AIOS platform" below. **Most active development happens here**, not in the four apps.

The books are the source material; the systems are production-quality implementations built from that knowledge.

---

## The AIOS platform (read this before changing anything under `aios_core/`, `brain/`, `second_brain/`, `learn_agent/`, `packs/`, `memory/`)

**The repository is the sole source of truth — there is no external state and conversation history is disposable (D13/P1).** Before editing platform code, read the canonical docs in order:
`START_HERE.md` → `PROJECT_CHARTER.md` (constitution: principles **P1–P10**, Definition of Done) → `AIOS_HANDBOOK.md` → `memory/state.md` · `plan.md` · `decisions.md` → `IMPLEMENTATION_PLAYBOOK.md` (milestones + **§V validation checklist**).

**Layering (dependencies point one way):**
```
learn_agent/ (AIOS product: Mission Control :8003, coach, teacher)  ─┐
brain/console/ (operator console :5052)                              │ apps
brain/skills/<id>/ (the skill LIBRARY: manifest.json + contracts)  ──┤ depend ONLY on
packs/<id>/ (self-contained domain packs, zero-core-change)         │  `from aios_core import ...`
        │                                                            │
        ▼                                                            │
aios_core/  ── the KERNEL: runtime/ (9-step dispatch lifecycle,      │
             registry, validator, executor, monitor) + sdk/ (six     │
             stable APIs: skill·workflow·agent·memory·retrieval·mission)
             + skill_sdk/ (skill authoring validator + quality score)│
        ▼                                                            │
second_brain/ ── knowledge pipeline; retrieval flows ONLY through    │
             gateway.py (scope→normalize→dedup→confidence→provenance)┘
memory/  ── notebook-first memory (files ARE the only durable state)
```

**Load-bearing rules (violating one is a bug even if code works):**
- **P1 files-are-memory**: all durable state is files under `memory/` (`state.md`=overwrite snapshot, `plan.md`=edit/prune, `log.md`=append ONE line/change ≤250 chars, `decisions.md`=append-only ADRs). Any session resumes from files alone. SQLite/`knowledge_cache.md` are rebuildable views, never source of truth (P2/D9).
- **P3/P9 retrieve-before-reason, scope-never-guessed**: knowledge claims trace to retrieved chunks; retrieval requires a mission or explicit `corpora` — no default corpus. New retrieval consumers go through `second_brain/gateway.py`; direct `Retriever` use elsewhere is a violation.
- **P8 model-agnostic**: no runtime/skill code names a vendor/model (test-enforced: `grep -riE 'fable|opus|sonnet|anthropic' brain/runtime/*.py aios_core/runtime/*.py` must be empty). Reasoning enters ONLY via adapters — `context["agent_adapter"]` (generative skills) or `context["task_executor"]` (planner). Model choice lives in `model_adapters/*.md` and optional `capability.json`, never in a manifest.
- **P10 thin surfaces**: routes/UIs only render skill/SDK outputs; business logic lives in skills/modules.
- **Skills**: `manifest.json` is the one machine format (12 required keys incl. `purpose`). The dispatcher enforces memory writes against the manifest allowlist (writes outside `write ∪ append_only` → `MEMORY_VIOLATION`). Generative skills are `runtime:agent` (or a python driver that requires an adapter) → `NOT_EXECUTABLE` without one; output is schema-validated so a weak model can't degrade a contract.

**Run the platform test suites** (the §V checklist in `IMPLEMENTATION_PLAYBOOK.md` — all must print `ALL PASS`; standalone scripts with exit codes, NOT pytest):
```bash
python3 second_brain/tests/test_pipeline.py          # + test_gateway.py
python3 aios_core/tests/test_aios_core.py             # + test_skill_sdk.py + test_capability.py
python3 brain/tests/test_runtime.py                   # + test_library_skills.py + test_console.py
python3 learn_agent/tests/test_aios_p0.py             # + test_mission_control.py + test_coach_service.py
python3 packs/tests/test_domain_packs.py
python3 brain/skills/recursive_planner/tests/test_skill_package.py
python3 docs/validate_repo_consistency.py             # repo self-consistency (skill count, ADR/§V drift)
```
**Author/validate a skill**: `python3 -m aios_core.skill_sdk.validator <skill_dir> full` must print `VALID` with quality ≥85 before registration in `brain/skills/registry.json`. New skills follow `templates/skill/` (full 11-file profile, D17).

**Definition of Done (any platform change)**: deterministic check written first and passing (P6) → all §V suites green → `memory/log.md` +1 line, `state.md` updated if a component changed, `decisions.md` only for irreversible choices → report evidence (file paths/outputs), not adjectives. Python **3.9** (use `Optional`, not `X | None`, in runtime-evaluated signatures).

---

## Running the Systems

### Agentic AI Brain (`brain/`)
General-purpose multi-agent orchestrator with 7 specialist agents, 5-type memory, and 9 tools.

```bash
cd brain
export ANTHROPIC_API_KEY=sk-ant-...
python3 cli.py                        # Interactive auto-mode
python3 cli.py "your task here"       # Single task
python3 cli.py --critique "task"      # With quality gate (critic agent)
```

### Vedic Astrology AI (`vedic_astro/`)
Chart calculation + 6-agent deep prediction engine + Flask web UI at **http://localhost:5050**.

```bash
cd vedic_astro
export ANTHROPIC_API_KEY=sk-ant-...
python3 cli.py                        # Terminal chatbot
python3 cli.py --demo                 # Gandhi's chart demo
python3 cli.py --ingest               # Rebuild book knowledge base (first run only)
python3 web/app.py                    # Web UI → http://localhost:5050
```

### Stock Agent AI (`stock_agent/`)
7-agent financial analysis pipeline (DeepSeek LLM) + Flask web UI at **http://localhost:5051**.

```bash
cd stock_agent
# Step 1: create .env with your DeepSeek key (platform.deepseek.com, ~$0.01/analysis)
echo "DEEPSEEK_API_KEY=sk-..." > .env
# Step 2: start server
python3 web/app.py                    # Web UI → http://localhost:5051
```

The server auto-loads `.env` on startup. No restart needed after adding the key if `.env` existed before launch.

### Health Vitals Agent (`health-agent/`)
```bash
cd health-agent
pip install -r requirements.txt
python3 main.py --demo
python3 main.py --input manual --data "HR=88 BP=145/92 SpO2=94 patient=P001"
python3 server.py                     # FastAPI server
```

### Dependencies
```bash
pip3 install anthropic pypdf pyswisseph geopy timezonefinder flask
pip3 install openai ta yfinance pandas                      # stock_agent extras
pip3 install fastapi uvicorn python-dotenv rich             # health-agent extras
```

---

## Architecture — Brain (`brain/`)

**Entry point:** `brain.py` → `Brain.think(task)` is the single public method.

**Request flow:**
```
cli.py → Brain.think()
  → _plan()           LLM classifies: simple|complex, single_agent|parallel|sequential
  → RouterAgent       fast Haiku model classifies intent → picks specialist agent
  → BaseAgent.run()   ReAct loop: LLM reasons → tool call → observe → loop
  → MemorySystem      stores event in episodic memory after completion
```

**Specialist agents** (all in `agents/specialist_agents.py`, all subclass `BaseAgent`):
`ResearchAgent`, `CodeAgent`, `DataAnalysisAgent`, `AppBuilderAgent`, `CriticAgent`, `ContentAgent`, `AssistantAgent`

**Memory** (`memory/memory_system.py`) — file-backed in `brain/data/memory/`:
`EpisodicMemory` (TF-IDF retrieval), `SemanticMemory` (key-value), `Blackboard` (cross-agent shared state)

**Tools** (`tools/tool_registry.py`): `web_search`, `read_file`, `write_file`, `run_python`, `run_shell`, `list_directory`, `get_datetime`, `calculate`, `create_agent_app`. Single dispatcher: `dispatch(tool_name, input_dict)`.

**Config** (`config.py`): `ORCHESTRATOR_MODEL = claude-sonnet-4-6`, `FAST_MODEL = claude-haiku-4-5-20251001`, `MAX_AGENT_STEPS = 20`.

---

## Architecture — Vedic Astrology (`vedic_astro/`)

**Two interfaces:** `cli.py` (terminal) and `web/app.py` (Flask, port 5050).

**Chart calculation flow:**
```
geocoder.py          place string → lat/lon/timezone (Nominatim, no API key)
chart/calculator.py  VedicChartCalculator → D-1 (Swiss Ephemeris, Lahiri ayanamsa, Whole Sign houses)
chart/divisional.py  build_divisional_charts(d1) → D-2, D-3, D-7, D-9, D-10
chart/formatter.py   South Indian ASCII grid + planet table + LLM context string
```

**Prediction flow** (`agents/prediction_engine.py`):
```
ChartContext.build_full_context()
  → analyze_career() / analyze_wealth() / analyze_relationships()
  → analyze_soul_purpose() / analyze_life_lessons()
  → synthesize_full_reading()   (6th LLM call — weaves all into one reading)
```
Each domain agent gets TF-IDF-retrieved passages from `knowledge/ingest.py` (10,358 chunks, 23 books, cached at `data/knowledge_base/knowledge_base.json`). Classical knowledge hardcoded in `knowledge/vedic_knowledge.py`.

**Web API** (`web/app.py`):
- `POST /api/geocode` — place → coordinates
- `POST /api/chart` — birth data → all charts as JSON
- `POST /api/reading/stream` — SSE, one event per domain section
- `POST /api/chat` — follow-up Q&A with chart context in memory

---

## Architecture — Stock Agent (`stock_agent/`)

**7-agent pipeline powered by DeepSeek `deepseek-chat` (OpenAI-compatible API).**

**Data flow:**
```
tools/market_data.py
  fetch_price_history()     yfinance OHLCV, 1-year history
  fetch_fundamentals()      40+ metrics (PE, margins, growth, analyst targets)
  fetch_recent_news()       Yahoo Finance news via yfinance
  fetch_reddit_sentiment()  public Reddit JSON API (r/wallstreetbets, r/stocks, r/investing)
  fetch_stocktwits_*()      StockTwits public API — bullish/bearish ratio
  compute_indicators()      15+ technical indicators via `ta` library
  compute_signal_summary()  composite bull/bear score 0-100
  compute_algo_signals()    Z-score mean reversion, momentum factor, linear regression,
                            historical volatility, Monte Carlo GBM (1000 paths, 30 days),
                            volume-price divergence, candlestick pattern detection
```

**Agent pipeline** (`agents/orchestrator.py` → `agents/stock_agents.py`):
```
1. ResearchAgent    — news + DuckDuckGo web search + macro context
2. FundamentalsAgent — valuation, earnings, analyst consensus
3. TechnicalAgent   — price action, indicators, entry/exit levels
4. RiskAgent        — volatility, position sizing, downside scenarios
5. SocialAgent      — Reddit, StockTwits, web forum sentiment
6. AlgoAgent        — interprets Z-score, momentum, Monte Carlo output
7. PredictionAgent  — final BUY/SELL/HOLD with entry/target/stop-loss as JSON
```

**Web server** (`web/app.py`, port 5051):
- `GET /api/status` — check if API key is loaded
- `POST /api/quick` — fast data-only response (no AI, <2s): indicators + algo signals + news + sparkline
- `POST /api/analyze/stream` — SSE stream, one progress event per agent stage, then full result JSON

**Key implementation details:**
- All agents call DeepSeek via `openai.OpenAI(base_url="https://api.deepseek.com")` — no Anthropic dependency
- `.env` file in `stock_agent/` is auto-loaded by `web/app.py` at startup (no dotenv package required — manual parse fallback)
- Pandas `Timestamp` keys in earnings/ratings data are sanitized via `_sanitize()` in `market_data.py` before JSON serialization
- The `/api/quick` endpoint works without any API key (pure yfinance + math)

---

## Architecture — Health Agent (`health-agent/`)

```
extractors/   screenshot.py | pdf_extractor.py | docx_extractor.py | manual_feed.py
                  ↓
agents/orchestrator.py       coordinates extraction + analysis
agents/threshold_checker.py  rule-based checks against config/thresholds.py
agents/llm_analyzer.py       LLM trend analysis + clinical interpretation
models/vitals.py             Pydantic VitalSigns model
```

---

## Key Patterns (reuse across systems)

| Pattern | Where implemented |
|---|---|
| ReAct loop | `brain/agents/base_agent.py` |
| Orchestrator → Router → Specialist | `brain/brain.py` → `RouterAgent` |
| Plan-and-Execute | `Brain._plan()` — JSON plan |
| Parallel agents | `Brain._execute_parallel()` — ThreadPoolExecutor |
| Self-correcting code | `CodeAgent` — reruns on error, 3 retries |
| SSE streaming | `vedic_astro/web/app.py`, `stock_agent/web/app.py` — threading.Queue → generator |
| TF-IDF RAG | `brain/memory/memory_system.py`, `vedic_astro/knowledge/ingest.py` |
| Social data scraping | `stock_agent/tools/market_data.py` — Reddit JSON API, StockTwits API |
| Monte Carlo simulation | `stock_agent/tools/market_data.py` `_monte_carlo_simulation()` — GBM |
| `.env` auto-load (no package) | `stock_agent/web/app.py` manual line-by-line parse |

---

## Synthesized Knowledge (Persistent Memory)

`~/.claude/projects/-Users-vaibhavgupta-Desktop-Agentic-AI/memory/`

- `reference_agent_design_patterns.md` — 21 patterns, MAS topologies, cognitive loop
- `reference_agent_protocols_frameworks.md` — MCP, A2A, LangGraph, CrewAI, AutoGen
- `reference_agent_production_engineering.md` — 10-step production stack, evaluation
- `reference_rag_memory_knowledge.md` — RAG variants, GraphRAG, vector DBs
- `reference_30_agents_catalog.md` — 30 agent types, L0-L5 progression

## Reading Books

```python
import pypdf
def read_pdf_pages(path, start=0, end=10):
    reader = pypdf.PdfReader(path)
    return "\n".join(reader.pages[i].extract_text() for i in range(start, min(end, len(reader.pages))))
```

EPUB files: extract as zip, read `content.opf` / HTML files inside.
