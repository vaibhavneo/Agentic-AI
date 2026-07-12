"""
Tests for stock_agent_analyze — hermetic, no model, no network. A stub SSE
collector injected via context["_sse_collector"] stands in for the real
HTTP call, per execution_contract.md's documented test seam.

Run: python3 brain/skills/stock_agent_analyze/tests/test_skill.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR.parents[2]
sys.path.insert(0, str(ROOT))

from aios_core import skill  # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def _collector(grouped):
    calls = []

    def fn(url, payload, terminal_events):
        calls.append((url, payload))
        return grouped
    fn.calls = calls
    return fn


def test_e1_happy_path():
    print("=== E1: happy path wraps the stub's 'result' event unchanged ===")
    result_payload = {"recommendation": "HOLD", "entry": 190.0}
    collector = _collector({"result": [result_payload], "done": [{}]})
    r = skill.run("stock_agent_analyze", {"ticker": "aapl"},
                  {"_sse_collector": collector})
    check("dispatch ok", r.ok, r.failure_detail)
    check("app == stock_agent", r.output.get("app") == "stock_agent")
    check("ticker upper-cased", r.output.get("ticker") == "AAPL")
    check("result passed through unchanged", r.output.get("result") == result_payload)


def test_e2_negative_missing_ticker():
    print("=== E2: missing 'ticker' -> INPUT_INVALID, never dispatched ===")
    collector = _collector({"result": [{"should": "never be called"}]})
    r = skill.run("stock_agent_analyze", {}, {"_sse_collector": collector})
    check("missing ticker -> INPUT_INVALID", r.failure == "INPUT_INVALID", str(r.failure))
    check("collector never invoked", collector.calls == [])


def test_e3_upstream_error_event_not_swallowed():
    print("=== E3: an upstream 'error' event surfaces, is not swallowed ===")
    collector = _collector({"error": [{"error": "No API key"}], "done": [{}]})
    r = skill.run("stock_agent_analyze", {"ticker": "x"}, {"_sse_collector": collector})
    check("upstream error -> EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))
    check("no fabricated ok=True", r.ok is False)


def test_e3b_missing_result_event_not_swallowed():
    print("=== E3b: a stream with no 'result' event surfaces, is not swallowed ===")
    collector = _collector({"progress": [{"stage": "data"}], "done": [{}]})
    r = skill.run("stock_agent_analyze", {"ticker": "x"}, {"_sse_collector": collector})
    check("missing result -> EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))


def test_stateless_no_memory_changes():
    print("=== stateless: no memory_changes recorded ===")
    collector = _collector({"result": [{"ok": True}], "done": [{}]})
    r = skill.run("stock_agent_analyze", {"ticker": "x"}, {"_sse_collector": collector})
    check("dispatch ok", r.ok, r.failure_detail)
    check("memory_changes empty", not getattr(r, "memory_changes", []))


if __name__ == "__main__":
    test_e1_happy_path()
    test_e2_negative_missing_ticker()
    test_e3_upstream_error_event_not_swallowed()
    test_e3b_missing_result_event_not_swallowed()
    test_stateless_no_memory_changes()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — stock_agent_analyze: HTTP pass-through, failures surface, stateless")
