"""Central configuration for the Agentic AI Brain."""
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).parent
DATA_DIR   = ROOT_DIR / "data"
MEMORY_DIR = DATA_DIR / "memory"

DATA_DIR.mkdir(exist_ok=True)
MEMORY_DIR.mkdir(exist_ok=True)

# ── Models ─────────────────────────────────────────────────────────────────
ORCHESTRATOR_MODEL = "claude-sonnet-4-6"   # planning + synthesis
FAST_MODEL         = "claude-haiku-4-5-20251001"  # routing, classification
CODE_MODEL         = "claude-sonnet-4-6"   # code generation / review

# ── Agent settings ─────────────────────────────────────────────────────────
MAX_AGENT_STEPS    = 20        # max ReAct iterations per task
MAX_RETRIES        = 3         # adaptive retry cap
TIMEOUT_SECONDS    = 120       # watchdog timeout per agent
PARALLEL_AGENTS    = 4         # max parallel sub-agent threads

# ── Memory settings ────────────────────────────────────────────────────────
MEMORY_TOP_K       = 5         # memories retrieved per lookup
MEMORY_MAX_TOKENS  = 2000      # max tokens injected from memory

# ── Anthropic ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
