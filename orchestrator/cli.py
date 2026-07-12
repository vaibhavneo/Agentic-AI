#!/usr/bin/env python3
"""
Central Orchestrator CLI (WP-O4, H-O5: CLI first).

Usage:
  python3 orchestrator/cli.py "Should I buy Apple stock right now?" \
      --app-inputs '{"ticker": "AAPL"}'
  python3 orchestrator/cli.py "Summarize the benefits of TF-IDF retrieval"

Routes the free-text task to one of 5 apps via the central_orchestrator
skill (Claude Fable 5 makes the routing decision; see fable_adapter.py —
the only file in this whole system naming that model, P8).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task", help="Free-text task to route")
    parser.add_argument("--app-inputs", default=None,
                        help="JSON object of structured inputs, required if routing "
                             "resolves to stock_agent_analyze / health_agent_analyze / "
                             "vedic_astro_reading")
    args = parser.parse_args()

    from aios_core import skill as _skill
    from orchestrator.fable_adapter import make_llm_adapter

    inputs = {"task": args.task}
    if args.app_inputs:
        inputs["app_inputs"] = json.loads(args.app_inputs)

    result = _skill.run("central_orchestrator", inputs,
                        {"agent_adapter": make_llm_adapter()})

    if not result.ok:
        print(f"FAILED [{result.failure}]: {result.failure_detail}", file=sys.stderr)
        return 1

    out = result.output
    print(f"Routed to: {out['skill_dispatched']}"
         f"{' (fallback)' if out['fallback_used'] else ''}")
    if out.get("reasoning"):
        print(f"Reasoning: {out['reasoning']}")
    print()
    print(json.dumps(out["result"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
