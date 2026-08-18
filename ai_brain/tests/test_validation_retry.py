"""Offline regression test for Milestone 3: load-bearing citation validation.

    python3 tests/test_validation_retry.py

No network, no API key: _validation_feedback() is pure, and professor_engine's
new feedback/stage plumbing is exercised against a fake client that captures
the prompt it was sent rather than calling the real DeepSeek API — proving
the retry actually carries the validator's specific complaints into the next
attempt, without needing a live model call. The live question (does a real
"fail" verdict actually trigger a rewrite end to end, and does it change the
answer) is a separate manual step, matching every other milestone's pattern
in this codebase.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import STAGE_PLAN, _validation_feedback, professor_engine

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


print("[_validation_feedback: turns a verdict into concrete instructions]")
check("empty when nothing to act on", _validation_feedback({}) == "")
check("empty when verdict has no unsupported_claims/contradicts_sources",
      _validation_feedback({"verdict": "fail", "fabricated_tags": ["S9"]}) == "")

fb = _validation_feedback({"unsupported_claims": ["the sky is green"]})
check("names the specific unsupported claim", "the sky is green" in fb, fb)
check("gives an instruction, not just the claim", "cite a real source" in fb, fb)

fb2 = _validation_feedback({"contradicts_sources": ["claims X but S1 says Y"]})
check("names the specific contradiction", "claims X but S1 says Y" in fb2, fb2)

fb3 = _validation_feedback({"unsupported_claims": ["claim A"],
                            "contradicts_sources": ["claim B"]})
check("both problem types included together", "claim A" in fb3 and "claim B" in fb3, fb3)
check("each problem is its own bullet line", fb3.count("\n- ") == 1 and fb3.startswith("- "),
      repr(fb3))

print("\n[professor_retry is a real, distinct stage — not silently missing from STAGE_PLAN]")
for depth in ("intro", "intermediate", "advanced"):
    check(f"professor_retry has a spec at {depth} depth",
          STAGE_PLAN["professor_retry"].get(depth) is not None)
    check(f"professor_retry matches professor's model/tokens at {depth} depth",
          STAGE_PLAN["professor_retry"][depth] == STAGE_PLAN["professor"][depth])


class _CapturingClient:
    """Fake DeepSeek client: no network, records the prompt it was sent and
    returns a canned successful response shaped like the real SDK's."""
    def __init__(self):
        self.last_user_prompt = None
        self.calls = []

        class _Usage:
            prompt_tokens = 10
            completion_tokens = 5
            completion_tokens_details = None

        class _Msg:
            content = "A rewritten answer."

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]
            usage = _Usage()

        self._resp = _Resp()

        class _Completions:
            def create(inner_self, model, max_tokens, messages):
                self.calls.append({"model": model, "max_tokens": max_tokens})
                self.last_user_prompt = messages[1]["content"]
                return self._resp

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class _Budget:
    def __init__(self):
        self.by_stage = {}
    def record(self, stage, model, usage, secs):
        self.by_stage[stage] = {"model": model}


print("\n[professor_engine wiring: feedback reaches the prompt, stage reaches the budget]")
client = _CapturingClient()
budget = _Budget()
result = professor_engine(
    "What is backpropagation?", {"restate": "q"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client, budget,
    topics=(), feedback="- Fix your fabricated claim about X.", stage="professor_retry")
check("the call actually returned the model's text", result == "A rewritten answer.", result)
check("feedback text reached the prompt sent to the model",
      "Fix your fabricated claim about X" in client.last_user_prompt)
check("the feedback is framed as a correction, not silently appended",
      "FAILED VALIDATION" in client.last_user_prompt)
check("budget recorded under the professor_retry stage name, not professor",
      "professor_retry" in budget.by_stage and "professor" not in budget.by_stage,
      str(budget.by_stage))

print("\n[professor_engine with no feedback — default stage, no correction text injected]")
client2 = _CapturingClient()
budget2 = _Budget()
professor_engine(
    "What is backpropagation?", {"restate": "q"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client2, budget2, topics=())
check("no correction framing when feedback is empty",
      "FAILED VALIDATION" not in client2.last_user_prompt)
check("defaults to the plain professor stage", "professor" in budget2.by_stage, str(budget2.by_stage))

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
