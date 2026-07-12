# Agentic AI

A personal workspace of agentic AI systems, plus the 60+ books and papers
that informed them. Everything here is either a standalone application or
part of **AIOS** — a reusable agent runtime the newer systems are built on.

## What's in here

| Directory | What it is |
|---|---|
| `brain/` | General-purpose multi-agent orchestrator — 7 specialist agents, file-backed memory, a ReAct tool-use loop |
| `vedic_astro/` | Vedic astrology chart calculator (Swiss Ephemeris) + a 6-agent deep-prediction engine, with a Flask web UI |
| `stock_agent/` | 7-agent financial analysis pipeline (fundamentals, technicals, risk, sentiment, algo signals) over a stock ticker |
| `health-agent/` | Health vitals extraction (screenshots/PDF/DOCX/manual) + threshold + LLM trend analysis |
| `feynman_agent/` | Feynman-technique physics tutor with retrieval over a physics book library |
| `orchestrator/` | **Central Orchestrator** — routes a free-text task to whichever of the 5 apps above should handle it |
| `aios_core/` + `second_brain/` + `brain/skills/` + `learn_agent/` + `packs/` | **AIOS** — the reusable agent platform: a manifest-driven skill runtime, a knowledge/retrieval pipeline, and an operator console |
| `memory/` | File-based, notebook-first memory for the AIOS platform — state, plans, decisions, and logs live here, not in any database |
| root-level PDFs/EPUBs | 60+ books on agentic AI, LLMs, multi-agent systems, and RAG — the source material behind the systems above |

## The Central Orchestrator

`orchestrator/` sits above all 5 applications and routes an arbitrary
free-text task to the right one, using Claude as the routing decision-maker.
Each app is wrapped as its own AIOS skill (`brain_think`, `stock_agent_analyze`,
`health_agent_analyze`, `vedic_astro_reading`, `feynman_ask`); the routing
skill (`central_orchestrator`) validates the model's choice against a known
app roster and falls back to the general-purpose `brain_think` if nothing
clearly matches, so a bad or hallucinated routing answer can never dispatch
to something that doesn't exist.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 orchestrator/cli.py "Should I buy Apple stock right now?" \
    --app-inputs '{"ticker": "AAPL"}'
```

## Running the standalone apps

```bash
# Brain — general-purpose orchestrator
cd brain && export ANTHROPIC_API_KEY=sk-ant-... && python3 cli.py

# Vedic Astrology — web UI at http://localhost:5050
cd vedic_astro && export ANTHROPIC_API_KEY=sk-ant-... && python3 web/app.py

# Stock Agent — web UI at http://localhost:5051 (needs a DeepSeek key in .env)
cd stock_agent && python3 web/app.py

# Health Agent
cd health-agent && pip install -r requirements.txt && python3 server.py
```

Each app carries its own `CLAUDE.md` with fuller setup/architecture notes.

## The AIOS platform

Most active development happens in AIOS, not the four standalone apps. It's
a manifest-driven **skill runtime**: every capability is a self-contained
skill package (`manifest.json` + contracts + schemas + tests) executed
through a 9-step dispatch lifecycle with typed failures and enforced memory
permissions. Reasoning enters only through an adapter seam — no runtime or
skill code names a specific model or vendor.

Start with [`START_HERE.md`](START_HERE.md), then
[`PROJECT_CHARTER.md`](PROJECT_CHARTER.md) for the governing principles, and
[`AIOS_HANDBOOK.md`](AIOS_HANDBOOK.md) for the full architecture.

```bash
# Validate a skill package
python3 -m aios_core.skill_sdk.validator <skill_dir> full

# Run the full platform regression suite
python3 docs/validate_repo_consistency.py
```

## Dependencies

```bash
pip3 install anthropic pypdf pyswisseph geopy timezonefinder flask
pip3 install openai ta yfinance pandas                      # stock_agent extras
pip3 install fastapi uvicorn python-dotenv rich             # health-agent extras
```
