"""Offline regression test for pipeline.py's _cap_question() — the defensive
length cap on the raw incoming question, added for paper_review mode (a
pasted paper draft could otherwise exceed the GET/EventSource transport and
understand()'s small token budget, per _call()'s own documented empty-
response failure mode).

    python3 tests/test_question_cap.py

No network, no API key: _cap_question() is a pure string function.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import _cap_question, _QUESTION_CHAR_CAP

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


print("[short/normal question: unchanged, not flagged as truncated]")
short = "What is backpropagation?"
out, truncated = _cap_question(short)
check("text unchanged", out == short)
check("truncated is False", truncated is False)

print("\n[question exactly at the cap: unchanged, not truncated]")
exact = "x" * _QUESTION_CHAR_CAP
out2, truncated2 = _cap_question(exact)
check("text unchanged at exactly the cap", out2 == exact)
check("truncated is False at exactly the cap (boundary is inclusive)", truncated2 is False)

print("\n[question one character over the cap: truncated to exactly the cap length]")
over = "x" * (_QUESTION_CHAR_CAP + 1)
out3, truncated3 = _cap_question(over)
check("output length is exactly the cap", len(out3) == _QUESTION_CHAR_CAP, str(len(out3)))
check("truncated is True", truncated3 is True)
check("output is a prefix of the input, not mangled", over.startswith(out3))

print("\n[a long pasted-paper-shaped input: truncated, flag set]")
paper = "Abstract: " + ("This paper investigates a novel method. " * 300)  # well over 6000 chars
out4, truncated4 = _cap_question(paper)
check("paper-length input gets truncated", truncated4 is True)
check("output capped at _QUESTION_CHAR_CAP", len(out4) <= _QUESTION_CHAR_CAP)

print("\n[custom cap argument is respected, not hardcoded]")
out5, truncated5 = _cap_question("x" * 100, cap=50)
check("respects a custom, smaller cap", len(out5) == 50 and truncated5 is True)

print("\n[empty string: unchanged, not truncated]")
out6, truncated6 = _cap_question("")
check("empty string stays empty", out6 == "")
check("empty string is not flagged as truncated", truncated6 is False)

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
