"""Offline regression test for the research-scientist capability's changes to
research.py's notebook: record() now stores sources on next_steps entries,
and brief() now surfaces proposed-but-not-yet-done next_steps into the
priming context fed back into future investigate() runs.

    python3 tests/test_research_notebook.py

No network, no API key: research.py's notebook functions are pure Python
against a JSON file, redirected to a scratch path for this run.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import research as R

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


_tmp = tempfile.TemporaryDirectory()
R.NOTEBOOK_PATH = Path(_tmp.name) / "notebook.json"

print("[record: next_steps now carry sources, same as findings/contradictions]")
R.record("attention-thread", next_step="read the Transformer paper", sources=["Attn Is All You Need"])
t = R.thread("attention-thread")
check("next_steps[0] has a sources field", "sources" in t["next_steps"][0])
check("sources value round-trips correctly",
      t["next_steps"][0]["sources"] == ["Attn Is All You Need"], str(t["next_steps"][0]))

print("\n[record: next_step with no sources arg defaults to an empty list, not missing/None]")
R.record("no-sources-thread", next_step="derive the identity")
t2 = R.thread("no-sources-thread")
check("sources defaults to []", t2["next_steps"][0]["sources"] == [], str(t2["next_steps"][0]))

print("\n[brief: surfaces proposed next_steps in a new labeled block]")
b = R.brief("attention-thread")
check("'Already proposed, not yet done' block is present", "Already proposed, not yet done" in b)
check("the specific proposed step text reaches the brief",
      "read the Transformer paper" in b)

print("\n[brief: no stray block when nothing has been proposed]")
R.record("findings-only-thread", finding="some established fact")
b2 = R.brief("findings-only-thread")
check("no 'Already proposed' block when next_steps is empty",
      "Already proposed" not in b2, b2)

print("\n[brief: still includes the existing findings/open_questions/contradictions blocks — not a regression]")
R.record("full-thread", finding="finding A", question="open question B", contradiction="conflict C")
R.record("full-thread", next_step="proposed step D")
b3 = R.brief("full-thread")
check("findings block present", "Established so far" in b3 and "finding A" in b3)
check("open questions block present", "Still open" in b3 and "open question B" in b3)
check("contradictions block present", "Unresolved contradictions" in b3 and "conflict C" in b3)
check("proposed-steps block present", "Already proposed" in b3 and "proposed step D" in b3)

print("\n[brief: an unknown/never-recorded thread returns an empty string, not an error]")
check("empty string for a thread that doesn't exist", R.brief("never-heard-of-this-thread") == "")

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
_tmp.cleanup()
sys.exit(1 if fails else 0)
