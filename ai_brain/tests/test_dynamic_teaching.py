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
check("challenge_idea -> thinking_partner",
      resolve_mode("challenge_idea", "auto") == "thinking_partner")
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
             "quiz", "teach_back", "whats_next", "why_chain", "research", "thinking_partner"}
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

print("\n[professor_engine: thinking_partner mode's directive actually reaches the prompt]")
from pipeline import _MODES_THAT_ALREADY_ASK
client9 = _CapturingClient()
professor_engine(
    "Challenge my idea to add a caching layer in front of the vector DB",
    {"restate": "q", "premise_check": "none"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "thinking_partner", "intermediate", client9, _Budget())
check("the thinking_partner directive text (not some other mode's) reaches the prompt",
      "thinking partner" in client9.last_user_prompt.lower()
      and "strongest objection" in client9.last_user_prompt)
check("thinking_partner is in the already-asks-a-question set (no stacked follow-up)",
      "thinking_partner" in _MODES_THAT_ALREADY_ASK)

print("\n[professor_engine: auto follow-up-question instruction, gated by mode]")
for m in ("explain", "compare", "deep_dive"):
    c = _CapturingClient()
    professor_engine("What is a gradient?", {"restate": "q", "premise_check": "none"},
                     {"kept": []}, {"hits": []}, None, {"skipped": True}, {"text": ""},
                     m, "intermediate", c, _Budget())
    check(f"follow-up instruction present for mode='{m}'",
          "follow-up question" in c.last_user_prompt)
for m in ("socratic", "quiz", "thinking_partner"):
    c = _CapturingClient()
    professor_engine("What is a gradient?", {"restate": "q", "premise_check": "none"},
                     {"kept": []}, {"hits": []}, None, {"skipped": True}, {"text": ""},
                     m, "intermediate", c, _Budget())
    check(f"no follow-up instruction for mode='{m}' (its own directive already asks one)",
          "follow-up question" not in c.last_user_prompt)

print("\n[professor_engine: KNOWN RECURRING MISCONCEPTION reaches the prompt when supplied]")
client10 = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q", "premise_check": "none"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client10, _Budget(), topics=(attention,),
    recurring_misconceptions=[{"topic_id": attention.id,
                               "misconception": "thinks attention is local-only", "n": 3,
                               "last_seen": "2026-08-01T00:00:00+00:00"}])
check("KNOWN RECURRING MISCONCEPTION block is present", "KNOWN RECURRING MISCONCEPTION" in client10.last_user_prompt)
check("the specific misconception text reaches the prompt",
      "thinks attention is local-only" in client10.last_user_prompt)
check("the repeat count reaches the prompt", "hit 3 times" in client10.last_user_prompt)

print("\n[professor_engine: no stray KNOWN RECURRING MISCONCEPTION block when none supplied]")
client11 = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q", "premise_check": "none"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client11, _Budget(), topics=(attention,))
check("no stray block when recurring_misconceptions wasn't supplied",
      "KNOWN RECURRING MISCONCEPTION" not in client11.last_user_prompt)

print("\n[professor_engine: memory_spine's 3 new context blocks (Phase 5) reach the prompt when populated]")
client12 = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q", "premise_check": "none"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client12, _Budget(), topics=(attention,),
    project_context="Project 'transformer-research': Goal: understand transformers deeply",
    kg_context="Attention and Scaled Dot-Product relates to: embeddings, transformer-architecture",
    research_context="Research thread 'attention-deep-dive': Established so far:\n  - a real finding")
check("RELEVANT PROJECT CONTEXT block present", "RELEVANT PROJECT CONTEXT" in client12.last_user_prompt)
check("the project's own brief text reaches the prompt",
      "understand transformers deeply" in client12.last_user_prompt)
check("RELATED CONCEPTS block present", "RELATED CONCEPTS" in client12.last_user_prompt)
check("the kg relation text reaches the prompt",
      "embeddings, transformer-architecture" in client12.last_user_prompt)
check("PRIOR RESEARCH ON THIS block present", "PRIOR RESEARCH ON THIS" in client12.last_user_prompt)
check("the research thread's own brief text reaches the prompt",
      "attention-deep-dive" in client12.last_user_prompt)

print("\n[professor_engine: the 3 new blocks are explicitly marked non-citable, like history already is]")
for label in ("RELEVANT PROJECT CONTEXT", "RELATED CONCEPTS", "PRIOR RESEARCH ON THIS"):
    idx = client12.last_user_prompt.index(label)
    line = client12.last_user_prompt[idx:idx + 80]
    check(f"'{label}' carries the same 'not a source, do not cite' framing RECENT CONVERSATION uses",
          "not a source, do not cite" in line, line)

print("\n[professor_engine: no stray new-context blocks when none of the 3 were supplied]")
client13 = _CapturingClient()
professor_engine(
    "What is attention?", {"restate": "q", "premise_check": "none"}, {"kept": []}, {"hits": []}, None,
    {"skipped": True}, {"text": ""}, "explain", "intermediate", client13, _Budget(), topics=(attention,))
for label in ("RELEVANT PROJECT CONTEXT", "RELATED CONCEPTS", "PRIOR RESEARCH ON THIS"):
    check(f"no stray {label} block when its data wasn't supplied", label not in client13.last_user_prompt)


class _JSONRespondingClient:
    """Like _CapturingClient, but the canned response content is
    configurable — needed to test understand()'s own JSON parsing (its
    idea_worthy field, specifically) rather than professor_engine()'s
    prompt construction, which is all _CapturingClient's fixed 'An
    answer.' response was ever built for."""
    def __init__(self, content: str):
        class _Usage:
            prompt_tokens = 10
            completion_tokens = 5
            completion_tokens_details = None
        class _Msg:
            pass
        class _Choice:
            message = _Msg()
            finish_reason = "stop"
        class _Resp:
            choices = [_Choice()]
            usage = _Usage()
        self._resp = _Resp()
        self._resp.choices[0].message.content = content

        class _Completions:
            def create(inner_self, model, max_tokens, messages):
                return self._resp
        class _Chat:
            completions = _Completions()
        self.chat = _Chat()


print("\n[understand: idea_worthy=true in the model's JSON reaches the returned dict]")
from pipeline import understand
u1 = understand("here's an idea for retrieval-first agents", "intermediate",
                _JSONRespondingClient('{"idea_worthy": true, "question_type": "challenge_idea"}'),
                _Budget())
check("idea_worthy is True when the model said true", u1["idea_worthy"] is True)

print("\n[understand: idea_worthy=false (the common case) reaches the returned dict]")
u2 = understand("what is attention", "intermediate",
                _JSONRespondingClient('{"idea_worthy": false, "question_type": "definition"}'),
                _Budget())
check("idea_worthy is False when the model said false", u2["idea_worthy"] is False)

print("\n[understand: idea_worthy defaults to False, not missing/None, when the model omits it]")
u3 = understand("what is attention", "intermediate",
                _JSONRespondingClient('{"question_type": "definition"}'),
                _Budget())
check("idea_worthy defaults to False (bool, not None)", u3["idea_worthy"] is False)

print("\n[understand: idea_worthy defaults to False on totally unparseable output, same as every other field]")
u4 = understand("what is attention", "intermediate",
                _JSONRespondingClient("not json at all"), _Budget())
check("idea_worthy still False, no crash", u4["idea_worthy"] is False)
check("question_type still falls back to 'general', same failure mode as every other field",
      u4["question_type"] == "general")

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
