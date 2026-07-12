"""
Reference driver for the stock_agent_analyze skill (v1.0.0).

HTTP wrapper around stock_agent/'s already-running server (D20: stock_agent
owns `agents/` and `tools/` packages that collide with brain/'s bare
top-level import names, confirmed empirically — HTTP avoids importing it
into the orchestrator's process at all). Consumes the SSE
`/api/analyze/stream` endpoint and returns its terminal `result` event.
No model or vendor is named here; stock_agent makes its own LLM calls
internally, invisible to this driver.
"""
from __future__ import annotations

import os

from aios_core.runtime.drivers._sse_client import collect_sse

DEFAULT_URL = "http://localhost:5051/api/analyze/stream"


def run(inputs: dict, context: dict) -> dict:
    context = context or {}
    ticker = inputs["ticker"].strip().upper()
    url = context.get("stock_agent_url") or os.environ.get(
        "STOCK_AGENT_URL", DEFAULT_URL)

    # Test seam: inject a stub SSE collector to stay hermetic (no network).
    collector = context.get("_sse_collector", collect_sse)
    grouped = collector(url, {"ticker": ticker}, terminal_events=("done",))

    if "error" in grouped:
        detail = grouped["error"][0].get("error", "unknown stock_agent error")
        raise RuntimeError(f"stock_agent returned an error: {detail}")
    if "result" not in grouped:
        raise RuntimeError(
            "stock_agent's stream ended without a 'result' event "
            f"(events seen: {sorted(grouped)})")

    result = grouped["result"][0]
    return {"app": "stock_agent", "ticker": ticker, "result": result}
