"""Offline regression test for making restated_computed_numbers load-bearing
(Milestone 6, second eval-suite finding).

    python3 tests/test_restated_numbers_verdict.py

Caught live: "What is 15% of 240?" got a real [T1] tool result (240*0.15 =
36.0), but the model computed the answer itself four different ways instead
of citing it — directly violating _PROF_SYS's explicit "never restate a
tool's digits" rule. validation()'s semantic pass already detects this
correctly (restated_computed_numbers: ["36.0"]) and even said so in its own
note, but that field never affected the verdict — only fabricated_tags did.
The answer came back "pass" anyway. No network needed here: a fake client
returns a canned JSON response shaped like the real semantic pass's output,
so the verdict-computation logic itself is provable without a live model
call — the same _CapturingClient-style pattern test_validation_retry.py and
test_prerequisite_scaffolding.py already established.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import validation

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


def _fake_client(json_reply: str):
    class _Usage:
        prompt_tokens = 10
        completion_tokens = 5
        completion_tokens_details = None

    class _Msg:
        content = json_reply

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    class _Completions:
        def create(self, model, max_tokens, messages):
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    return _Client()


class _Budget:
    def __init__(self):
        self.by_stage = {}
    def record(self, stage, model, usage, secs):
        self.by_stage[stage] = {"model": model}


TOOL_RES = {"ok": True, "expression": "240*0.15", "result": 36.0}
PROSE = "15% of 240 is 36 [T1], computed by breaking 240 into 2.4 hundreds times 15."

print("[the exact real case: semantic pass says 'pass' but flags a restated number]")
client = _fake_client(
    '{"verdict":"pass","note":"ties the result to T1, honest",'
    '"unsupported_claims":[],"contradicts_sources":[],'
    '"restated_computed_numbers":["36.0"]}')
checks = validation("What is 15% of 240?", PROSE, {"kept": []}, {"hits": []}, TOOL_RES,
                    "intermediate", client, _Budget(), topics=())
check("restated_computed_numbers is captured", checks["restated_computed_numbers"] == ["36.0"],
      str(checks["restated_computed_numbers"]))
check("verdict is forced to caution despite the semantic pass saying pass",
      checks["verdict"] == "caution", checks["verdict"])

print("\n[no restated numbers, semantic pass says pass — stays pass]")
client2 = _fake_client(
    '{"verdict":"pass","note":"","unsupported_claims":[],"contradicts_sources":[],'
    '"restated_computed_numbers":[]}')
checks2 = validation("What is backpropagation?", "Backpropagation applies the chain rule [S1].",
                     {"kept": [{"tag": "S1", "source": "x", "text": "y"}]}, {"hits": []}, None,
                     "intermediate", client2, _Budget(), topics=())
check("verdict stays pass when nothing is restated", checks2["verdict"] == "pass", checks2["verdict"])

print("\n[restated numbers AND the semantic pass already said fail — still fail, not downgraded]")
client3 = _fake_client(
    '{"verdict":"fail","note":"contradicts a source","unsupported_claims":[],'
    '"contradicts_sources":["claims X but S1 says Y"],"restated_computed_numbers":["36.0"]}')
checks3 = validation("q", PROSE, {"kept": []}, {"hits": []}, TOOL_RES,
                     "intermediate", client3, _Budget(), topics=())
check("a genuine fail is not softened to caution by also having a restated number",
      checks3["verdict"] == "fail", checks3["verdict"])

print("\n[restated numbers alongside a fabricated tag — still just caution, not a new tier]")
client4 = _fake_client(
    '{"verdict":"pass","note":"","unsupported_claims":[],"contradicts_sources":[],'
    '"restated_computed_numbers":["36.0"]}')
checks4 = validation("q", "36 [T1] [S9]", {"kept": []}, {"hits": []}, TOOL_RES,
                     "intermediate", client4, _Budget(), topics=())
check("fabricated_tags picked up S9 (not offered)", checks4["fabricated_tags"] == ["S9"],
      str(checks4["fabricated_tags"]))
check("verdict is caution, not some third tier", checks4["verdict"] == "caution", checks4["verdict"])

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
