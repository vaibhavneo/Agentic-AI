"""
Tests for health_agent_analyze — hermetic, no model, no network. A stub HTTP
poster injected via context["_http_post"] stands in for the real HTTP call,
per execution_contract.md's documented test seam.

Run: python3 brain/skills/health_agent_analyze/tests/test_skill.py
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


def _poster(status, body):
    calls = []

    def fn(url, payload):
        calls.append((url, payload))
        return status, body
    fn.calls = calls
    return fn


def test_e1_happy_path():
    print("=== E1: happy path wraps the stub's 200 body unchanged ===")
    body = {"flags": ["elevated_bp"], "hr": 88}
    poster = _poster(200, body)
    r = skill.run("health_agent_analyze", {"text": "HR=88 BP=145/92 SpO2=94"},
                  {"_http_post": poster})
    check("dispatch ok", r.ok, r.failure_detail)
    check("app == health_agent", r.output.get("app") == "health_agent")
    check("result passed through unchanged", r.output.get("result") == body)


def test_e2_negative_missing_text():
    print("=== E2: missing 'text' -> INPUT_INVALID, never dispatched ===")
    poster = _poster(200, {"should": "never be called"})
    r = skill.run("health_agent_analyze", {}, {"_http_post": poster})
    check("missing text -> INPUT_INVALID", r.failure == "INPUT_INVALID", str(r.failure))
    check("poster never invoked", poster.calls == [])


def test_e3_http_error_status_not_swallowed():
    print("=== E3: a 4xx/5xx status surfaces, is not swallowed ===")
    poster = _poster(500, {"detail": "internal error"})
    r = skill.run("health_agent_analyze", {"text": "x"}, {"_http_post": poster})
    check("500 status -> EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))
    check("no fabricated ok=True", r.ok is False)


def test_e3b_embedded_error_key_not_swallowed():
    print("=== E3b: a 200 body with an embedded 'error' key surfaces, is not swallowed ===")
    poster = _poster(200, {"error": "Unsupported file type"})
    r = skill.run("health_agent_analyze", {"text": "x"}, {"_http_post": poster})
    check("embedded error -> EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))


def test_stateless_no_memory_changes():
    print("=== stateless: no memory_changes recorded ===")
    poster = _poster(200, {"ok": True})
    r = skill.run("health_agent_analyze", {"text": "x"}, {"_http_post": poster})
    check("dispatch ok", r.ok, r.failure_detail)
    check("memory_changes empty", not getattr(r, "memory_changes", []))


if __name__ == "__main__":
    test_e1_happy_path()
    test_e2_negative_missing_text()
    test_e3_http_error_status_not_swallowed()
    test_e3b_embedded_error_key_not_swallowed()
    test_stateless_no_memory_changes()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — health_agent_analyze: HTTP pass-through, failures surface, stateless")
