"""Offline regression test for Milestone 2 Step 2: retrieval-informed web
escalation.

    python3 tests/test_web_escalation.py

No network, no API key: _should_escalate_web() and _mark_web_escalated() are
pure functions over synthetic routing/evidence dicts. The live question --
does an escalation actually call web_search() and does the badge flip to
"web reference only" -- is a separate manual before/after step against a
running instance, matching Milestone 1's own precedent (test the logic
offline, verify the live effect separately, since every pipeline stage in
this codebase calls the real API with no mock layer anywhere).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import _mark_web_escalated, _should_escalate_web

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


def routing(web=False, why=None):
    return {"books": True, "web": web, "tools": False,
            "why": why or ["books: always — the library is the primary source",
                            "web: not needed — no time-sensitive element",
                            "tools: not needed — nothing to compute"]}


NO_BOOKS = {"kept": []}
HAS_BOOKS = {"kept": [{"tag": "S1", "text": "x"}]}
# retrieve_evidence()'s own early-error paths return {"kept": [], "rejected": [],
# "available": False} without ever setting evidence_strength — the exact case
# _should_escalate_web must still catch (checking `kept` directly rather than
# evidence_strength == "none").
LIBRARY_DOWN = {"available": False, "reason": "ModuleNotFoundError", "kept": [], "rejected": []}

print("[fires: books empty, web not already routed, non-intro depth]")
check("intermediate depth", _should_escalate_web(routing(web=False), NO_BOOKS, "intermediate"))
check("advanced depth", _should_escalate_web(routing(web=False), NO_BOOKS, "advanced"))
check("fires on a total library outage, not just a clean empty result",
      _should_escalate_web(routing(web=False), LIBRARY_DOWN, "intermediate"))

print("\n[does not fire: any one guard condition blocks it]")
check("does not fire at intro depth even with empty books",
      not _should_escalate_web(routing(web=False), NO_BOOKS, "intro"))
check("does not fire when web was already being fetched (no double-fetch)",
      not _should_escalate_web(routing(web=True), NO_BOOKS, "intermediate"))
check("does not fire when books have real evidence",
      not _should_escalate_web(routing(web=False), HAS_BOOKS, "intermediate"))
check("does not fire when both books have evidence and web already routed",
      not _should_escalate_web(routing(web=True), HAS_BOOKS, "advanced"))

print("\n[_mark_web_escalated rewrites routing state exactly]")
r = routing(web=False)
_mark_web_escalated(r)
check("web flips to True", r["web"] is True)
check("the web line in why is replaced with the escalation reason",
      "web: escalated — book search returned nothing" in r["why"], str(r["why"]))
check("the books/tools why lines are untouched",
      r["why"][0] == "books: always — the library is the primary source" and
      r["why"][2] == "tools: not needed — nothing to compute", str(r["why"]))
check("why still has exactly 3 lines (rewrite, not append)", len(r["why"]) == 3, str(len(r["why"])))

r2 = routing(web=False, why=["books: always — the library is the primary source",
                              "web: skipped — intro depth",
                              "tools: skipped — intro depth"])
_mark_web_escalated(r2)
check("rewrites the intro-skip wording too, not just the 'not needed' wording",
      r2["why"][1] == "web: escalated — book search returned nothing", str(r2["why"]))

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
