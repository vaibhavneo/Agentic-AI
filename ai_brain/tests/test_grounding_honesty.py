"""Offline regression test for the grounding-honesty fix (Milestone 1).

    python3 tests/test_grounding_honesty.py

No network, no API key: reasoning_engine()'s new empty-evidence guard
returns before ever touching the LLM client, so this proves the guard logic
itself without needing a real DeepSeek call — the live before/after (does
the header actually read right, does the call count actually drop) is a
separate, manual step documented in the plan, since every stage in this
pipeline calls the real API with no mock layer anywhere in this codebase.

This is the regression tripwire for the bug: retrieval coming back empty
used to still trigger a reasoning call with "SOURCES:\n(none)" — wasted
work that risked priming the final answer to sound structured about
material that doesn't exist, and was the reason the observed 91s/12,702-
token case had 4 LLM calls instead of the 3 it needs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import reasoning_engine

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


NO_BOOK, NO_WEB, NO_TOOL = {"kept": []}, {"hits": []}, None
UNDERSTANDING = {"restate": "q"}


class _UnreachableClient:
    """Any attribute access means the guard failed to skip and the code
    tried to make a real call — fail loudly instead of hanging on a network
    call that has no API key to succeed with."""
    def __getattr__(self, name):
        raise AssertionError(f"reasoning_engine reached the LLM client (.{name}) "
                              "despite empty evidence — the skip guard did not fire")


print("[empty evidence — the exact bug scenario]")
for depth in ("intermediate", "advanced"):
    r = reasoning_engine("q", UNDERSTANDING, NO_BOOK, NO_WEB, NO_TOOL, {},
                          depth, _UnreachableClient(), budget=None)
    check(f"{depth}: skips when nothing was retrieved", r.get("skipped") is True, str(r))
    check(f"{depth}: reason names the actual cause",
          r.get("reason") == "no book, web or tool evidence — nothing to build a reasoning skeleton from",
          r.get("reason"))
    check(f"{depth}: text is empty on skip", r.get("text") == "")

print("\n[tool_res present but not ok — must not count as evidence]")
r = reasoning_engine("q", UNDERSTANDING, NO_BOOK, NO_WEB, {"ok": False}, {},
                      "intermediate", _UnreachableClient(), budget=None)
check("still skips", r.get("skipped") is True, str(r))

print("\n[intro depth — original skip reason must be preserved, unrelated to evidence]")
r = reasoning_engine("q", UNDERSTANDING,
                      {"kept": [{"tag": "S1", "source": "Book", "text": "real evidence"}]},
                      NO_WEB, NO_TOOL, {}, "intro", _UnreachableClient(), budget=None)
check("still skips at intro even with real evidence", r.get("skipped") is True, str(r))
check("for the intro reason, not the empty-evidence reason",
      r.get("reason") == "intro depth — reasoning folded into the teaching stage", r.get("reason"))

print("\n[evidence present at non-intro depth — must NOT skip, must reach the LLM]")
for label, book, web, tool in [
    ("book evidence", {"kept": [{"tag": "S1", "source": "Book", "text": "x"}]}, NO_WEB, NO_TOOL),
    ("web evidence", NO_BOOK, {"hits": [{"title": "t", "snippet": "s"}]}, NO_TOOL),
    ("tool evidence", NO_BOOK, NO_WEB, {"ok": True, "expression": "2+2", "result": 4}),
]:
    reached = False
    try:
        reasoning_engine("q", UNDERSTANDING, book, web, tool, {}, "intermediate",
                          _UnreachableClient(), budget=None)
    except AssertionError:
        reached = True
    check(f"{label}: guard does not fire, reaches the real call path", reached)

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
