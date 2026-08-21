"""Offline regression test for the "personal AI professor" intelligence
upgrade's pipeline changes: resolve_mode()'s auto-strategy selection, and
professor_engine's new context blocks (TEACHING PROGRESSION, RECENTLY
STUDIED, RECOMMENDED TOPICS, TEACH-BACK EVALUATION, PREMISE CHECK) actually
reaching the prompt.

    python3 tests/test_dynamic_teaching.py

No network, no API key: same _CapturingClient fake test_validation_retry.py
and test_prerequisite_scaffolding.py established, which records the prompt
sent to the model instead of calling the real API.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import curriculum as CUR
from pipeline import resolve_mode, professor_engine, MODE_DIRECTIVE

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


print("[resolve_mode: question_type drives the teaching strategy when mode=auto]")
check("teach_me -> deep_dive", resolve_mode("teach_me", "auto") == "deep_dive")
check("deep_dive -> deep_dive", resolve_mode("deep_dive", "auto") == "deep_dive")
check("compare -> compare", resolve_mode("compare", "auto") == "compare")
check("derivation -> derivation", resolve_mode("derivation", "auto") == "derivation")
check("worked_example -> exercise (reuses the existing exercise mode)",
      resolve_mode("worked_example", "auto") == "exercise")
check("quiz_me -> quiz", resolve_mode("quiz_me", "auto") == "quiz")
check("teach_back -> teach_back", resolve_mode("teach_back", "auto") == "teach_back")
check("whats_next -> whats_next", resolve_mode("whats_next", "auto") == "whats_next")
check("why_chain -> why_chain", resolve_mode("why_chain", "auto") == "why_chain")
check("research -> research", resolve_mode("research", "auto") == "research")
check("definition -> deep_dive (the spec's own 'What is attention?' example — "
      "a bare 'what is X' still gets the progressive treatment, not a one-liner)",
      resolve_mode("definition", "auto") == "deep_dive")
check("unrecognized question_type falls back to explain",
      resolve_mode("something_new", "auto") == "explain")
check("empty requested_mode also defers to auto-selection",
      resolve_mode("teach_me", "") == "deep_dive")

print("\n[resolve_mode: an explicit dropdown choice always wins over the classifier]")
check("socratic picked on purpose beats a teach_me classification",
      resolve_mode("teach_me", "socratic") == "socratic")
check("explain picked on purpose beats a whats_next classification",
      resolve_mode("whats_next", "explain") == "explain")

print("\n[every mode resolve_mode can produce has a real MODE_DIRECTIVE entry]")
_ALL_MODES = {"explain", "socratic", "exercise", "compare", "deep_dive", "derivation",
             "quiz", "teach_back", "whats_next", "why_chain", "research"}
for m in _ALL_MODES:
    check(f"MODE_DIRECTIVE has an entry for '{m}'", m in MODE_DIRECTIVE and len(MODE_DIRECTIVE[m]) > 20)


class _CapturingClient:
    def __init__(self):
        self.last_user_prompt = None

        class _Usage:
            prompt_tokens = 10
            completion_tokens = 5
            completion_tokens_details = None

        class _Msg:
            content = "An answer."

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]
            usage = _Usage()

        self._resp = _Resp()

        class _Completions:
            def create(inner_self, model, max_tokens, messages):
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


attention = CUR.TOPICS["attention-mechanism"]
embeddings = CUR.TOPICS["embeddings"]
optimizers = CUR.TOPICS["optimizers"]

print("\n[professor_engine: TEACHING PROGRESSION reaches the prompt, already-known marked]")
client = _CapturingClient()
professor_engine(
    "Teach me attention", {"restate": "q", "premise_check": "none"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "deep_dive", "intermediate", client, _Budget(),
    topics=(attention,), progression=(embeddings, attention), known_ids={embeddings.id})
check("TEACHING PROGRESSION block is present", "TEACHING PROGRESSION" in client.last_user_prompt)
check("the already-known step is marked", "ALREADY KNOWN" in client.last_user_prompt)
check("both progression steps' tags are in the prompt (citable)",
      f"[C:{embeddings.id}]" in client.last_user_prompt and f"[C:{attention.id}]" in client.last_user_prompt)

print("\n[professor_engine: RECENTLY STUDIED reaches the prompt]")
client2 = _CapturingClient()
professor_engine(
    "What is optimizers?", {"restate": "q", "premise_check": "none"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client2, _Budget(),
    topics=(optimizers,), recent_topics=(embeddings,))
check("RECENTLY STUDIED block present with the recent topic's title",
      "RECENTLY STUDIED" in client2.last_user_prompt and embeddings.title in client2.last_user_prompt)

print("\n[professor_engine: RECOMMENDED TOPICS reaches the prompt for whats_next]")
client3 = _CapturingClient()
professor_engine(
    "What should I learn next?", {"restate": "q", "premise_check": "none"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "whats_next", "intermediate", client3, _Budget(),
    topics=(), recommended_topics=(embeddings, optimizers))
check("RECOMMENDED TOPICS block present", "RECOMMENDED TOPICS" in client3.last_user_prompt)
check("recommended topics' tags are citable",
      f"[C:{embeddings.id}]" in client3.last_user_prompt and f"[C:{optimizers.id}]" in client3.last_user_prompt)

print("\n[professor_engine: TEACH-BACK EVALUATION reaches the prompt]")
client4 = _CapturingClient()
professor_engine(
    "Attention lets tokens look at nearby tokens only", {"restate": "q", "premise_check": "none"},
    {"kept": []}, {"hits": []}, None, {"skipped": True}, {"text": ""}, "teach_back", "intermediate",
    client4, _Budget(), topics=(attention,),
    teachback_eval={"correctness": "incorrect",
                   "misconceptions": ["claims attention only looks at nearby tokens"],
                   "confirmed": []})
check("TEACH-BACK EVALUATION block present", "TEACH-BACK EVALUATION" in client4.last_user_prompt)
check("the specific misconception text reaches the prompt",
      "only looks at nearby tokens" in client4.last_user_prompt)

print("\n[professor_engine: PREMISE CHECK reaches the prompt when understand() flagged one]")
client5 = _CapturingClient()
professor_engine(
    "Since attention always uses more compute than RNNs, why bother?",
    {"restate": "q", "premise_check": "misconception",
     "premise_note": "attention is not always more expensive than an RNN at inference"},
    {"kept": []}, {"hits": []}, None, {"skipped": True}, {"text": ""}, "explain", "intermediate",
    client5, _Budget(), topics=(attention,))
check("PREMISE CHECK block present", "PREMISE CHECK" in client5.last_user_prompt)
check("the specific premise note reaches the prompt",
      "not always more expensive" in client5.last_user_prompt)

print("\n[professor_engine: no premise issue — no stray PREMISE CHECK block]")
client6 = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q", "premise_check": "none", "premise_note": ""},
    {"kept": []}, {"hits": []}, None, {"skipped": True}, {"text": ""}, "explain", "intermediate",
    client6, _Budget(), topics=(attention,))
check("no PREMISE CHECK block when premise_check is 'none'",
      "PREMISE CHECK" not in client6.last_user_prompt)

print("\n[professor_engine: no new blocks when nothing was passed — fully backward compatible]")
client7 = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client7, _Budget(), topics=(attention,))
for label in ("TEACHING PROGRESSION", "RECENTLY STUDIED", "RECOMMENDED TOPICS", "TEACH-BACK EVALUATION"):
    check(f"no stray {label} block when its data wasn't supplied", label not in client7.last_user_prompt)
check("no stray RECENT CONVERSATION block when history wasn't supplied",
      "RECENT CONVERSATION" not in client7.last_user_prompt)

print("\n[session persistence: _format_history]")
from pipeline import _format_history
_hist = [
    {"role": "user", "content": "What is a gradient?"},
    {"role": "assistant", "content": "x" * 400},
    {"role": "user", "content": "Why does it point uphill?"},
    {"role": "assistant", "content": "By definition of the directional derivative."},
]
check("empty history -> empty block", _format_history(()) == "")
check("malformed pairs (no assistant reply) -> empty block",
      _format_history([{"role": "user", "content": "q"}]) == "")
one_turn = _format_history(_hist, max_turns=1)
check("max_turns=1 keeps only the most recent exchange",
      "Why does it point uphill" in one_turn and "What is a gradient" not in one_turn)
check("long answers are truncated", "x" * 400 not in _format_history(_hist, max_turns=2))
two_turns = _format_history(_hist, max_turns=2)
check("max_turns=2 keeps both exchanges",
      "What is a gradient" in two_turns and "Why does it point uphill" in two_turns)

print("\n[professor_engine: RECENT CONVERSATION reaches the prompt when history is supplied]")
client8 = _CapturingClient()
professor_engine(
    "Why does it point uphill?", {"restate": "q", "premise_check": "none"},
    {"kept": []}, {"hits": []}, None, {"skipped": True}, {"text": ""}, "explain", "intermediate",
    client8, _Budget(), topics=(attention,), history=_hist)
check("RECENT CONVERSATION block is present", "RECENT CONVERSATION" in client8.last_user_prompt)
check("the prior question reaches the prompt", "What is a gradient?" in client8.last_user_prompt)

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
