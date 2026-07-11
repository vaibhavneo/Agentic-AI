#!/usr/bin/env python3
"""
Agentic AI Brain — Interactive CLI
====================================
The complete agentic AI system in auto mode.
Just type your task — the brain handles everything.

Usage:
  python cli.py                        # interactive mode
  python cli.py "your task here"       # single task mode
  python cli.py --critique "task"      # with quality gate

Hotkeys (interactive mode):
  /help      — show commands
  /memory    — show recent memory
  /stats     — session statistics
  /facts     — stored semantic facts
  /critique  — toggle auto quality gate
  /clear     — clear screen
  /quit      — exit
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

# ── ensure brain package is importable ────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))


BANNER = r"""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║    █████╗  ██████╗ ███████╗███╗   ██╗████████╗██╗ ██████╗       ║
║   ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝██║██╔════╝       ║
║   ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ██║██║            ║
║   ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ██║██║            ║
║   ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ██║╚██████╗       ║
║   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝ ╚═════╝       ║
║                                                                  ║
║         AI BRAIN  ·  Powered by 60 Books + Claude               ║
║   Research · Code · Build Apps · Analyze · Create · Solve        ║
╚══════════════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """
┌─────────────────────────────────────────────────────────┐
│                    BRAIN COMMANDS                       │
├─────────────────────────────────────────────────────────┤
│  Just type your task — Brain handles everything.        │
│                                                         │
│  COMMANDS:                                              │
│  /help       Show this help                             │
│  /memory     Show recent episodic memory                │
│  /facts      Show stored knowledge facts                │
│  /stats      Session statistics                         │
│  /critique   Toggle auto quality-gate (critic agent)    │
│  /clear      Clear the screen                           │
│  /quit       Exit                                       │
│                                                         │
│  EXAMPLES:                                              │
│  › Research the latest advances in quantum computing    │
│  › Write a Python web scraper for Hacker News           │
│  › Build a RAG chatbot app and save it to ~/Desktop     │
│  › Analyze this CSV: ~/data/sales.csv                   │
│  › Write a blog post about autonomous AI agents         │
│  › What is the difference between MCP and A2A?          │
│  › Create a multi-agent system that writes and reviews  │
└─────────────────────────────────────────────────────────┘
"""

def _hr(char="─", width=68):
    return char * width

def _wrap(text: str, width: int = 80, indent: str = "") -> str:
    paragraphs = text.split("\n")
    wrapped = []
    for para in paragraphs:
        if not para.strip():
            wrapped.append("")
        elif para.startswith(("#", "-", "*", ">", "|", "```", "  ")):
            wrapped.append(indent + para)
        else:
            wrapped.extend(
                textwrap.wrap(para, width=width - len(indent),
                              initial_indent=indent, subsequent_indent=indent)
            )
    return "\n".join(wrapped)


def run_cli():
    print(BANNER)

    # ── Import brain (deferred so import errors show clearly)
    try:
        from brain import Brain
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure you're in the brain/ directory and have anthropic installed:")
        print("   pip install anthropic")
        sys.exit(1)

    # ── Check API key
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("❌  ANTHROPIC_API_KEY not set.")
        print("    Run: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # ── Init brain
    print("⚡ Initializing Brain... ", end="", flush=True)
    try:
        brain = Brain(api_key=api_key, verbose=True)
        print("Ready!\n")
    except Exception as e:
        print(f"\n❌ Failed to initialize: {e}")
        sys.exit(1)

    print("Type your task and press Enter. /help for commands.\n")
    print(_hr())

    auto_critique = False

    # ── Single-task mode (CLI arg)
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        if args[0] == "--critique":
            auto_critique = True
            args = args[1:]
        task = " ".join(args)
        if task:
            print(f"\n📥 Task: {task}\n{_hr()}")
            result = brain.think(task, auto_critique=auto_critique)
            print(f"\n{_hr()}")
            print("📤 Result:\n")
            print(_wrap(result))
            print(f"\n{_hr()}")
            return

    # ── Interactive mode
    while True:
        try:
            user_input = input("\n🧠 You → ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye! 👋")
            break

        if not user_input:
            continue

        # ── Commands
        cmd = user_input.lower()

        if cmd in ("/quit", "/exit", "/q"):
            print("\nGoodbye! 👋")
            break

        elif cmd == "/help":
            print(HELP_TEXT)
            continue

        elif cmd == "/clear":
            os.system("clear" if os.name != "nt" else "cls")
            print(BANNER)
            continue

        elif cmd == "/stats":
            stats = brain.stats()
            if not stats:
                print("No tasks run yet.")
            else:
                print(f"\n📊 Session Statistics")
                print(_hr())
                for k, v in stats.items():
                    if isinstance(v, float):
                        print(f"  {k}: {v:.2f}")
                    else:
                        print(f"  {k}: {v}")
            continue

        elif cmd == "/memory":
            recent = brain.memory.episodic.recent(8)
            if not recent:
                print("No memory yet.")
            else:
                print(f"\n📚 Recent Memory ({len(recent)} events)")
                print(_hr())
                for e in recent:
                    ts = e.get("timestamp", "")[:16]
                    print(f"  [{ts}] {e['type']}: {e['content'][:120]}")
            continue

        elif cmd == "/facts":
            facts = brain.memory.semantic._facts[-10:]
            if not facts:
                print("No stored facts yet.")
            else:
                print(f"\n🔖 Stored Knowledge ({len(brain.memory.semantic._facts)} total)")
                print(_hr())
                for f in facts:
                    print(f"  • {f['key']}: {f['value'][:100]}")
            continue

        elif cmd == "/critique":
            auto_critique = not auto_critique
            state = "ON" if auto_critique else "OFF"
            print(f"🔍 Auto quality-gate: {state}")
            continue

        elif cmd.startswith("/"):
            print(f"Unknown command: {user_input}. Type /help for commands.")
            continue

        # ── Task execution
        print(f"\n{_hr()}")
        try:
            result = brain.think(user_input, auto_critique=auto_critique)
            print(f"\n{_hr('═')}")
            print("📤 Answer:\n")
            print(_wrap(result, width=80))
            print(f"\n{_hr('═')}")
        except KeyboardInterrupt:
            print("\n\n⚡ Interrupted.")
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    run_cli()
