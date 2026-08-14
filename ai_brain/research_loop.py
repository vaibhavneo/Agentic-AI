"""Autonomous research loop.

    prior context → search (library + arXiv) → synthesise → NAME THE GAP
                  → propose the next concrete step → record

The stage that makes this research rather than summarising is the gap: the
run is required to state what is *not* established and what would settle it.
A loop that only summarises produces a longer summary each time; a loop that
names gaps and proposes steps accumulates.

Everything is appended to a notebook thread, so a scheduled run reads what
previous runs concluded and continues instead of restarting. That persistence
is the whole point — without it, "autonomous research" is just a cron job that
re-asks the same question.

Cost follows the same discipline as the teaching pipeline: the survey and
recording stages run on flash, and only the synthesis — where the reasoning
actually matters — is allowed the expensive model, and only at depth.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

import research as R
from brain_tutor import MODEL_DEEP, MODEL_FAST, _api_key, retrieve_evidence
from pipeline import Budget, _call, _json_from

# stage → (model, max_tokens) by depth, same philosophy as pipeline.STAGE_PLAN
# Sized for the reasoning, not the prose. A research prompt carries six paper
# abstracts plus eight book passages — 14k+ characters — and the model reasons
# in proportion: a survey call at 3,000 tokens spent all 3,000 on reasoning and
# returned nothing. These budgets leave room for the chain of thought as well
# as the answer; _call also retries once at double if a stage still comes back
# empty.
LOOP_PLAN = {
    "survey":    {"intro": (MODEL_FAST, 6000),  "intermediate": (MODEL_FAST, 8000),
                  "advanced": (MODEL_FAST, 10000)},
    "synthesis": {"intro": (MODEL_FAST, 12000), "intermediate": (MODEL_FAST, 20000),
                  "advanced": (MODEL_DEEP, 28000)},
    "gap":       {"intro": (MODEL_FAST, 6000),  "intermediate": (MODEL_FAST, 8000),
                  "advanced": (MODEL_DEEP, 12000)},
}


def _plan(stage, depth):
    return LOOP_PLAN[stage].get(depth, LOOP_PLAN[stage]["intermediate"])


_SURVEY_SYS = """You are the survey stage of a research loop. Read the material \
and reply with ONLY JSON:

{"established":["claims the material genuinely supports, each concrete"],
 "disputed":["points where sources disagree or hedge, naming the tag"],
 "dated":["claims that look time-sensitive and may have moved on"],
 "irrelevant":["tags that do not bear on the question"]}

Be strict. A source sharing vocabulary with the question is irrelevant."""

_SYNTH_SYS = """You are the synthesis stage of a research loop. Write the current \
state of understanding on this question for a researcher who already knows the \
field.

Cite tags inline — [S#] library, [A#] arXiv paper, [P#] prior finding from this \
thread. Distinguish what is established from what is merely widely repeated. \
Where the literature and the textbooks disagree, say so and say which is more \
recent. Do not pad; a researcher wants the shape of the problem, not a primer.

CRITICAL: if no [A#] papers were supplied, you have NOT consulted the primary \
literature. Do not write a section describing what "the literature establishes" \
in that case — say plainly that no papers were retrieved and that what follows \
is recalled from training, which may be out of date. Attributing your own \
recall to a literature search you did not perform is the single worst failure \
this pipeline can produce.

Use LaTeX for mathematics."""

_GAP_SYS = """You are the gap stage. You have a synthesis of the current state. \
Reply with ONLY JSON:

{"gaps":["what is NOT established — be specific, not 'more research is needed'"],
 "contradictions":["direct conflicts between sources worth resolving"],
 "next_steps":[{"step":"one concrete action","why":"what it would settle",
                "kind":"derive|compute|read|experiment|search"}],
 "derivable":["any claim that could be checked symbolically, as an equation"],
 "confidence":"high|medium|low"}

A good next step is something that could actually be done next session — read a
named paper, derive a stated identity, compute a specific quantity. Reject
vague suggestions."""


def investigate(thread: str, question: str, depth: str = "intermediate",
                use_arxiv: bool = True) -> Iterator[tuple[str, dict]]:
    """One research iteration on a thread. Yields (stage, payload)."""
    key = _api_key()
    if not key:
        yield "error", {"message": "No DEEPSEEK_API_KEY found"}
        return
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com",
                    timeout=300.0, max_retries=1)
    budget = Budget()
    t_start = time.monotonic()

    # 1 ── prior context: what previous runs concluded
    prior = R.brief(thread)
    prev = R.thread(thread)
    yield "recall", {
        "msg": (f"{len(prev.get('findings', []))} prior finding(s), "
                f"{sum(1 for q in prev.get('open_questions', []) if q.get('status') == 'open')} open question(s)")
        if prev else "new thread — no prior context",
        "thread": thread, "has_prior": bool(prior)}

    # 2 ── gather library + literature in parallel
    yield "search", {"msg": "Searching library and arXiv…"}
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_lib = pool.submit(retrieve_evidence, question)
        f_arx = pool.submit(R.search_arxiv, question, 6, "relevance") if use_arxiv else None
        lib = f_lib.result()
        arx = f_arx.result() if f_arx else {"ok": True, "papers": []}
    papers = arx.get("papers", [])
    yield "search", {"msg": (f"{len(lib.get('kept', []))} library passage(s), "
                             f"{len(papers)} paper(s)"
                             + (f", newest {arx.get('newest')}" if papers else "")
                             + f" · {int((time.monotonic()-t0)*1000)}ms"),
                     "library": lib, "arxiv": arx}

    # tag everything once so every later stage cites the same labels
    def material():
        parts = []
        for c in lib.get("kept", []):
            parts.append(f"[{c['tag']}] BOOK · {c['source']} ({c['shelf']})\n{c['text'][:900]}")
        for i, p in enumerate(papers, 1):
            parts.append(f"[A{i}] ARXIV {p['published']} · {p['title']}\n{p['summary'][:900]}")
        for i, f in enumerate(prev.get("findings", [])[-5:], 1):
            parts.append(f"[P{i}] PRIOR FINDING ({f['at'][:10]}) · {f['text']}")
        return "\n\n".join(parts) or "(no material found)"

    mat = material()

    # 3 ── survey
    yield "survey", {"msg": "Sorting established from disputed…"}
    survey = _json_from(_call(client, "survey", depth, _SURVEY_SYS,
                              f"QUESTION: {question}\n\nMATERIAL:\n{mat}",
                              budget, force=_plan("survey", depth)), {})
    for k in ("established", "disputed", "dated", "irrelevant"):
        survey.setdefault(k, [])
    yield "survey", {"msg": (f"{len(survey['established'])} established · "
                             f"{len(survey['disputed'])} disputed · "
                             f"{len(survey['dated'])} possibly dated"),
                     "survey": survey}

    # 4 ── synthesis
    yield "synthesis", {"msg": "Writing the current state of understanding…"}
    t_s = time.monotonic()
    synthesis = _call(
        client, "synthesis", depth, _SYNTH_SYS,
        f"QUESTION: {question}\n\n"
        + (f"WHAT THIS THREAD ALREADY CONCLUDED:\n{prior}\n\n" if prior else "")
        + f"SURVEY: established={survey['established']} disputed={survey['disputed']} "
          f"dated={survey['dated']}\n\nMATERIAL:\n{mat}\n\nWrite the synthesis now.",
        budget, force=_plan("synthesis", depth))
    if not synthesis.strip():
        yield "error", {"message": "synthesis stage returned nothing"}
        return
    yield "synthesis", {"msg": f"{len(synthesis.split())} words in {int(time.monotonic()-t_s)}s"}

    # 5 ── the gap: what is NOT known, and what to do next
    yield "gap", {"msg": "Identifying what is not established…"}
    gap = _json_from(_call(client, "gap", depth, _GAP_SYS,
                           f"QUESTION: {question}\n\nSYNTHESIS:\n{synthesis[:7000]}",
                           budget, force=_plan("gap", depth)), {})
    for k in ("gaps", "contradictions", "next_steps", "derivable"):
        gap.setdefault(k, [])
    gap.setdefault("confidence", "medium")
    yield "gap", {"msg": (f"{len(gap['gaps'])} gap(s) · {len(gap['next_steps'])} next step(s) · "
                          f"confidence {gap['confidence']}"), "gap": gap}

    # 6 ── verify anything the gap stage says is checkable
    verified = []
    for claim in gap["derivable"][:3]:
        if "=" in claim:
            lhs, _, rhs = claim.partition("=")
            chk = R.check_identity(lhs.strip(), rhs.strip())
            if chk.get("ok"):
                verified.append({"claim": claim, "verdict": chk["verdict"],
                                 "equal": chk["equal"]})
    if verified:
        yield "verify", {"msg": f"{sum(1 for v in verified if v['equal'])}/{len(verified)} "
                                f"symbolic claim(s) hold", "verified": verified}

    # 7 ── record: this is what makes the next run a continuation
    for f in survey["established"][:4]:
        R.record(thread, finding=f, sources=[p["title"][:60] for p in papers[:2]])
    for g in gap["gaps"][:4]:
        R.record(thread, question=g)
    for c in gap["contradictions"][:3]:
        R.record(thread, contradiction=c)
    for st in gap["next_steps"][:4]:
        R.record(thread, next_step=f"[{st.get('kind', 'read')}] {st.get('step', '')} "
                                   f"— {st.get('why', '')}")
    state = R.thread(thread)
    yield "record", {"msg": (f"thread now holds {len(state.get('findings', []))} finding(s), "
                             f"{len(state.get('next_steps', []))} proposed step(s)"),
                     "thread_state": {k: len(v) for k, v in state.items()
                                      if isinstance(v, list)}}

    yield "done", {
        "thread": thread, "question": question, "depth": depth,
        "synthesis": synthesis, "survey": survey, "gap": gap,
        "verified": verified, "library": lib, "arxiv": arx,
        "budget": budget.summary(), "elapsed_s": int(time.monotonic() - t_start),
        "honesty": {
            "papers_consulted": len(papers),
            "newest_paper": arx.get("newest"),
            "library_passages": len(lib.get("kept", [])),
            "note": ("[S] your books · [A] arXiv preprint · [P] a prior finding "
                     "from this thread. Untagged text is the model's synthesis."),
        },
    }


def run_once(thread: str, question: str, depth: str = "intermediate") -> dict:
    last: dict = {}
    for stage, payload in investigate(thread, question, depth):
        if stage in ("done", "error"):
            last = {"stage": stage, **payload}
    return last


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: research_loop.py <thread> <question> [depth]")
        raise SystemExit(2)
    th, q = sys.argv[1], sys.argv[2]
    dp = sys.argv[3] if len(sys.argv) > 3 else "intermediate"
    for stage, p in investigate(th, q, dp):
        if stage == "done":
            print("\n" + "=" * 68)
            print(p["synthesis"])
            print("=" * 68)
            print("\nGAPS:")
            for g in p["gap"]["gaps"]:
                print("  -", g)
            print("\nNEXT STEPS:")
            for s in p["gap"]["next_steps"]:
                print(f"  [{s.get('kind')}] {s.get('step')}")
            b = p["budget"]
            print(f"\n{b['llm_calls']} calls · {b['total_tokens']:,} tokens · {p['elapsed_s']}s")
        elif stage == "error":
            print("ERROR:", p)
        else:
            print(f"  [{stage}] {p.get('msg', '')}")
