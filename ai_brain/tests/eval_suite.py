"""Answer-quality regression suite for AI Brain — Milestone 6.

    python3 tests/eval_suite.py [base-url]
    (defaults to http://127.0.0.1:5000; pass a deployed URL to run against
    production, same convention as smoke_deployment.py)

smoke_deployment.py asks "is the deployment reachable and computing
correctly" — Brain Lab math, curriculum matching, one streaming call. This
suite asks a narrower, different question: across a curated set of
questions chosen to exercise DIFFERENT pipeline behaviors (well-grounded,
prerequisite-scaffolded, tool-computed, deliberately off-topic, each
teaching mode), does the app stay honest and well-formed? Every assertion
is structural, not semantic — "did a fabricated tag slip through," "does
the grounding badge's claim match what evidence actually returned," "did
an off-topic question correctly refuse to match" — the same kind of closed-
form check this codebase already uses everywhere, not an LLM grading the
prose (that's a different, harder problem this suite deliberately doesn't
attempt).

Costs real API tokens and wall-clock time — this is a live suite against
the real DeepSeek API, not something to run in a tight loop. Run it after
a change that could plausibly affect answer honesty or structure, not on
every commit.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000").rstrip("/")

fails = []
results = []


def check(label, ok, detail=""):
    print(f"    {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


def ask(question, mode="explain", depth="intermediate", timeout=200):
    q = urllib.parse.urlencode({"q": question, "mode": mode, "depth": depth})
    try:
        with urllib.request.urlopen(BASE + "/api/ask?" + q, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
    # socket.timeout is a distinct exception from the builtin TimeoutError on
    # Python < 3.10 (they only became aliases in 3.10) — a slow response body
    # (connection succeeds, but reading stalls past `timeout`) raised past an
    # except clause that only caught URLError/TimeoutError and crashed the
    # whole suite instead of recording one failed case and moving on.
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, str(e)
    done = [ln for ln in text.splitlines() if ln.startswith("data: ") and '"honesty"' in ln]
    if not done:
        return None, "no 'done' event with honesty in the stream"
    try:
        return json.loads(done[-1][len("data: "):]), None
    except json.JSONDecodeError as e:
        return None, f"bad JSON in done event: {e}"


def cited_tags(prose):
    return set(re.findall(r"\[((?:C:[\w\-]+)|(?:[SWT]\d+))\]", prose or ""))


# Each case names the pipeline behavior it exercises and a list of
# (label, fn(d) -> bool) structural checks specific to that behavior, on
# top of the universal checks every case gets regardless (see run_case).
CASES = [
    {
        "name": "well-grounded book question",
        "question": "What is backpropagation and how does the chain rule apply?",
        "mode": "explain", "depth": "intermediate",
        "checks": [
            ("grounded in real library evidence",
             lambda d: d["honesty"]["grounded_in_library"] is True),
            ("at least one real [S#] citation, not curriculum-only",
             lambda d: any(t.startswith("S") for t in cited_tags(d["prose"]))),
        ],
    },
    {
        "name": "prerequisite-scaffolded question (Milestone 4)",
        "question": "Why does attention divide the dot product by sqrt(d_k)?",
        "mode": "explain", "depth": "intro",
        "checks": [
            ("topics matched", lambda d: len(d.get("topics", [])) > 0),
            ("prereq_topics field present (even if empty — proves the field ships)",
             lambda d: "prereq_topics" in d),
        ],
    },
    {
        "name": "tool-computed question",
        "question": "What is 15% of 240?",
        # route() deliberately skips tools at intro depth to save tokens
        # (tools = needs_compute and depth != "intro") — this needs
        # intermediate or the tool branch never fires at all, which is
        # what the suite's first run actually caught: not a pipeline bug,
        # a wrong assumption in this test itself.
        "mode": "explain", "depth": "intermediate",
        "checks": [
            ("tool result computed", lambda d: bool(d.get("tool") and d["tool"].get("ok"))),
            ("honesty.used_tools is true", lambda d: d["honesty"]["used_tools"] is True),
            # Whether THIS run's model phrasing counts as "restating" a
            # digit is validation()'s own semantic judgment call, not
            # something a prose regex here can reliably re-derive (an
            # earlier version of this check matched "36" as a substring of
            # any nearby number, and disagreed with the validator's own
            # more careful judgment about legitimate explanatory arithmetic
            # vs. an independent recomputation). What IS a deterministic
            # guarantee, proven separately offline in
            # test_restated_numbers_verdict.py, is the *consequence* if it
            # is flagged — assert that implication holds live too, without
            # requiring this specific run's phrasing to trigger it.
            ("if a digit was flagged as restated, the verdict reflects it (caution, not pass)",
             lambda d: d["validation"].get("verdict") != "pass"
                       if d["validation"].get("restated_computed_numbers") else True),
        ],
    },
    {
        "name": "deliberately off-topic question (caught a real bug — see _filter_off_topic)",
        "question": "What is the best pizza topping combination in Naples?",
        # Intermediate, not intro: evidence_engine (and therefore off_topic
        # classification) is skipped entirely at intro depth to save
        # tokens, so the off-topic filter this case exists to test simply
        # never engages there — a real, still-open gap, not something this
        # depth choice papers over (see _filter_off_topic's docstring).
        "mode": "explain", "depth": "intermediate",
        "checks": [
            ("curriculum correctly matches nothing", lambda d: len(d.get("topics", [])) == 0),
            # This exact question is what found the off_topic-never-filtered
            # bug: BM25 genuinely matches a Python tutorial's `pizza = {...}`
            # dict example and a RAG demo's test query on pure vocabulary
            # overlap. evidence_engine's off-topic classification is itself
            # an LLM judgment call and won't always catch every incidental
            # match in one pass (confirmed across live runs: it caught 2 of
            # 8, then 6 of 8, on the same question) — asserting it clears
            # ALL 8 every single run conflates "the mechanism exists and
            # engages" with "the classifier has perfect recall," which no
            # single LLM call guarantees. What's actually deterministic,
            # proven offline in test_off_topic_filter.py, is that whatever
            # off_topic DOES name gets excluded. Assert that engagement
            # here, not 100% completeness.
            ("evidence_engine actually classified this obviously off-topic library "
             "content as off_topic (the mechanism engaged, not just existed)",
             lambda d: len(d.get("assessment", {}).get("off_topic", [])) > 0),
        ],
    },
    {
        "name": "compare mode — structural teaching move, not just style",
        "question": "Compare L1 and L2 regularization.",
        "mode": "compare", "depth": "intro",
        "checks": [
            ("answer is non-trivial length", lambda d: len(d["prose"]) > 200),
        ],
    },
    {
        "name": "socratic mode",
        "question": "What is overfitting?",
        "mode": "socratic", "depth": "intro",
        "checks": [
            ("contains at least one question mark (guided questioning)",
             lambda d: "?" in d["prose"]),
        ],
    },
]


def run_case(case):
    print(f"\n[{case['name']}] {case['question']!r} (mode={case['mode']}, depth={case['depth']})")
    d, err = ask(case["question"], case["mode"], case["depth"])
    if d is None:
        check(f"{case['name']}: got a response at all", False, err)
        return

    # Universal checks every case gets, regardless of what it's specifically
    # probing — these are the cross-cutting honesty/structure invariants
    # Milestones 1-4 were about.
    check("prose is non-empty", bool((d.get("prose") or "").strip()))
    check("validation.fabricated_tags is empty — no citation claims a source that wasn't offered",
          not d.get("validation", {}).get("fabricated_tags"),
          str(d.get("validation", {}).get("fabricated_tags")))
    check("validation.verdict is a real value, not missing",
          d.get("validation", {}).get("verdict") in ("pass", "caution", "fail"),
          str(d.get("validation", {}).get("verdict")))
    check("honesty block is present with all four source-type flags",
          all(k in d.get("honesty", {}) for k in
              ("grounded_in_library", "covered_by_curriculum", "used_web", "used_tools")))
    # If validation retried and still failed, that's worth knowing about
    # loudly, not silently passing the suite.
    v = d.get("validation", {})
    if v.get("verdict") == "fail":
        check(f"{case['name']}: verdict is 'fail' even after any retry — investigate", False,
              f"retried={v.get('retried')}, unsupported={v.get('unsupported_claims')}, "
              f"contradicts={v.get('contradicts_sources')}")

    for label, fn in case["checks"]:
        try:
            check(label, bool(fn(d)))
        except Exception as exc:
            check(label, False, f"assertion raised {type(exc).__name__}: {exc}")

    results.append({"case": case["name"], "elapsed_s": d.get("elapsed_s"),
                    "llm_calls": d.get("budget", {}).get("llm_calls"), "verdict": v.get("verdict")})


print(f"=== AI Brain eval suite against {BASE} ===")
for case in CASES:
    run_case(case)

print(f"\n=== summary ===")
for r in results:
    print(f"  {r['case']:<45s} {r['elapsed_s']:>4}s  {r['llm_calls']:>2} calls  verdict={r['verdict']}")

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
