"""
Instruction controls (mode + depth) are functional end to end:
  - resolve_turn() auto-detects mode/depth from wording on ANY turn ("auto"),
    and an explicit dropdown selection always wins.
  - the teacher adapter injects the correct behavioral directive for the chosen
    mode + depth into the model prompt (so the lesson actually changes), and
    scales the token budget by depth.

Deterministic: the adapter test captures a stub call_llm's arguments — no real
model. Run: python3 learn_agent/tests/test_instruction_modes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "learn_agent"))
sys.path.insert(0, str(ROOT / "brain" / "console"))

import teach_session as ts           # noqa: E402
import teacher_adapter               # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


# ── resolve_turn: auto-detection + explicit override ───────────────────────

def test_auto_detects_on_fresh_turn():
    print("=== resolve_turn: 'auto' infers mode/depth from wording (fresh turn) ===")
    r = ts.resolve_turn({}, "compare VAEs and GANs")
    check("fresh 'compare X and Y' -> compare mode", r["mode"] == "compare", r["mode"])
    r = ts.resolve_turn({}, "quiz me on backpropagation")
    check("fresh 'quiz me' -> exercise mode", r["mode"] == "exercise", r["mode"])
    r = ts.resolve_turn({}, "explain diffusion models simply")
    check("fresh 'simply' -> intro depth", r["depth"] == "intro", r["depth"])
    r = ts.resolve_turn({}, "show me the full derivation of the ELBO")
    check("fresh 'derivation' -> advanced depth", r["depth"] == "advanced", r["depth"])


def test_plain_question_uses_defaults():
    print("=== resolve_turn: a plain question falls back to explain/intermediate ===")
    r = ts.resolve_turn({}, "What is a transformer?")
    check("plain fresh question -> explain", r["mode"] == "explain", r["mode"])
    check("plain fresh question -> intermediate", r["depth"] == "intermediate", r["depth"])


def test_long_question_with_that_is_fresh_topic():
    """The reported bug: a long NEW question that merely contains 'that' was
    misread as a follow-up and answered the PREVIOUS topic. It must be fresh."""
    print("=== resolve_turn: a long question with 'that' is a fresh topic, not a follow-up ===")
    session = {"last_topic": "how AI predicts stock prices"}
    msg = ("what are some of the specific highly advanced mathematical topics "
           "that will help me build strong AI systems and intelligent agents")
    r = ts.resolve_turn(session, msg)
    check("not treated as a follow-up", r["is_followup"] is False, str(r["is_followup"]))
    check("topic is the NEW question, not the old one", r["topic"] == msg, r["topic"])


def test_short_refinement_is_followup():
    """Genuine short refinements still thread onto the current topic."""
    print("=== resolve_turn: short pure refinements remain follow-ups ===")
    session = {"last_topic": "gradient descent"}
    for m in ["simpler please", "now show the math", "explain that again", "quiz me on it"]:
        r = ts.resolve_turn(session, m)
        check(f"'{m}' -> follow-up on gradient descent",
              r["is_followup"] and r["topic"] == "gradient descent", str(r))


def test_new_named_topic_is_fresh_even_if_short():
    """A short message that names its OWN subject (e.g. 'compare VAEs and GANs')
    is a fresh topic, not a refinement of the previous one."""
    print("=== resolve_turn: a short but subject-bearing message is fresh ===")
    session = {"last_topic": "gradient descent"}
    r = ts.resolve_turn(session, "compare VAEs and GANs")
    check("names new subjects -> fresh topic", r["is_followup"] is False, str(r))
    check("topic is the new question", r["topic"] == "compare VAEs and GANs", r["topic"])
    check("still auto-selects compare mode", r["mode"] == "compare", r["mode"])


def test_explicit_dropdown_wins():
    print("=== resolve_turn: an explicit dropdown selection overrides keywords ===")
    # message says 'compare' but the user explicitly picked socratic + advanced.
    r = ts.resolve_turn({}, "compare A and B", explicit_mode="socratic", explicit_depth="advanced")
    check("explicit mode wins over keyword", r["mode"] == "socratic", r["mode"])
    check("explicit depth wins over keyword", r["depth"] == "advanced", r["depth"])


# ── teacher adapter: mode/depth directives reach the model prompt ──────────

def _capture_adapter():
    seen = {}

    def fake_call_llm(messages, system, max_tokens):
        seen["user"] = messages[-1]["content"]
        seen["system"] = system
        seen["max_tokens"] = max_tokens
        # The delimited output format the adapter now expects — deliberately
        # includes an unescaped inner "quote" and a stray backslash \\alpha to
        # prove content that would break strict JSON parses cleanly here.
        return ('<<<EXPLANATION>>>\nx uses the "attention" trick and \\alpha term\n'
                '<<<EXERCISE_PROMPT>>>\np\n<<<EXERCISE_KIND>>>\nrecall\n'
                '<<<MASTERY_QUESTION>>>\nq\n<<<MASTERY_SIGNAL>>>\ns\n'
                '<<<PRINCIPLE>>>\npr\n<<<WHEN_TO_USE>>>\nw\n')
    adapter = teacher_adapter.make_llm_adapter(call_llm=fake_call_llm)
    return adapter, seen


def test_adapter_injects_mode_directive():
    print("=== adapter: each mode injects its distinct behavioral directive ===")
    for mode, needle in [("socratic", "guided questioning"),
                         ("exercise", "Practice-first"),
                         ("compare", "comparison"),
                         ("explain", "ground-up explanation")]:
        adapter, seen = _capture_adapter()
        adapter({"id": "teacher"}, {"topic": "T", "mode": mode, "depth": "intermediate",
                                    "adaptation": {"level": "introduce"}, "source_evidence": []}, {})
        check(f"mode '{mode}' directive present", needle.lower() in seen["user"].lower(),
              needle)


def test_adapter_injects_depth_directive_and_scales_tokens():
    print("=== adapter: depth changes both the directive and the token budget ===")
    budgets = {}
    for depth, needle in [("intro", "no background"),
                          ("intermediate", "basic ML familiarity"),
                          ("advanced", "full")]:
        adapter, seen = _capture_adapter()
        adapter({"id": "teacher"}, {"topic": "T", "mode": "explain", "depth": depth,
                                    "adaptation": {"level": "introduce"}, "source_evidence": []}, {})
        check(f"depth '{depth}' directive present", needle.lower() in seen["user"].lower(), needle)
        budgets[depth] = seen["max_tokens"]
    check("advanced gets the largest token budget",
          budgets["advanced"] > budgets["intermediate"] > budgets["intro"], str(budgets))


def test_adapter_auto_defaults_are_safe():
    print("=== adapter: unknown/None mode+depth fall back without crashing ===")
    adapter, seen = _capture_adapter()
    out = adapter({"id": "teacher"}, {"topic": "T", "mode": None, "depth": None,
                                      "adaptation": {}, "source_evidence": []}, {})
    check("returns the five adapter keys",
          all(k in out for k in ("explanation", "exercise", "mastery_check",
                                 "principle", "when_to_use")))
    check("defaults to explain directive", "ground-up explanation" in seen["user"].lower())
    check("defaults to intermediate directive", "basic ml familiarity" in seen["user"].lower())


def test_delimited_parse_survives_json_breaking_content():
    """The exact failure that 502'd before: content with an unescaped inner
    quote AND a stray backslash. Delimited parsing must sail through it."""
    print("=== adapter: quotes/backslashes/newlines in content no longer break parsing ===")
    adapter, _ = _capture_adapter()   # fake_call_llm returns such content
    out = adapter({"id": "teacher"}, {"topic": "T", "mode": "explain", "depth": "intermediate",
                                      "adaptation": {}, "source_evidence": []}, {})
    check("inner quote preserved verbatim", '"attention"' in out["explanation"], out["explanation"])
    check("stray backslash preserved verbatim", "\\alpha" in out["explanation"], out["explanation"])
    check("exercise kind parsed", out["exercise"]["kind"] == "recall")
    check("mastery signal parsed", out["mastery_check"]["expected_signal"] == "s")


def test_parser_tolerates_bracket_slips():
    """The model is sloppy with the closing fence — 3, 2, or zero closing
    brackets, and markdown decoration — all must still parse; inline '<' in math
    must NOT be mistaken for a marker."""
    print("=== parser: tolerant of <<<X>>> / <<<X>> / bare <<<X and markdown decoration ===")
    import teacher_adapter as ta
    for label, raw in [
        ("three brackets", "<<<EXPLANATION>>>\nA.\n"),
        ("two brackets", "<<<EXPLANATION>>\nA.\n"),
        ("no closing", "<<<EXPLANATION\nA long enough lesson body here.\n"),
        ("markdown-decorated", "**<<< EXPLANATION >>>**\nA.\n"),
    ]:
        d = ta._parse_delimited(raw)
        check(f"{label} -> EXPLANATION captured", bool(d.get("EXPLANATION")), str(d))
    body = "<<<EXPLANATION>>>\np(x)=Π p(x_t | x_<t) stays in the body.\n"
    d = ta._parse_delimited(body)
    check("inline '<' in math not mistaken for a marker",
          "x_<t" in d.get("EXPLANATION", ""), d.get("EXPLANATION", ""))


if __name__ == "__main__":
    for t in [test_auto_detects_on_fresh_turn, test_plain_question_uses_defaults,
              test_long_question_with_that_is_fresh_topic,
              test_short_refinement_is_followup,
              test_new_named_topic_is_fresh_even_if_short,
              test_explicit_dropdown_wins, test_adapter_injects_mode_directive,
              test_adapter_injects_depth_directive_and_scales_tokens,
              test_adapter_auto_defaults_are_safe,
              test_delimited_parse_survives_json_breaking_content,
              test_parser_tolerates_bracket_slips]:
        t()
    print("=" * 58)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — instruction mode/depth is functional end to end")
