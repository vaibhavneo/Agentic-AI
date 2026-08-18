"""AI Brain pipeline — the nine-stage flow.

    USER → UNDERSTAND → ROUTER → { BOOKS | WEB | TOOLS }
         → EVIDENCE (verify/compare) → REASONING → PROFESSOR
         → VALIDATION → ANSWER

Each stage is a generator step so the caller can stream it; the trace is the
product, not debug output.

Token discipline
----------------
DeepSeek publishes exactly two models — deepseek-v4-flash and deepseek-v4-pro
— so "one model per depth" is not available. Spending is controlled instead by
which *stage* gets the expensive model, which saves far more than a per-depth
split would: most stages here are short classification or checking work that
flash does as well as pro, and only the reasoning and teaching stages benefit
from deliberation.

    stage        basic          intermediate     advanced
    understand   flash  600     flash    600     flash    800
    route        free (rules)   free             free
    evidence     skipped        flash   1500     flash   2500
    reasoning    skipped        flash   4000     PRO    12000
    professor    flash 5000     flash  10000     PRO    16000
    validation   free (rules)   flash   1200     flash   1800
                 ──────────     ──────────       ──────────
    LLM calls    2              5                5

Basic also skips the web and tool branches entirely, so a simple question
costs two short flash calls rather than a full fan-out.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

import curriculum as CUR
from brain_tutor import (BRAIN_CORPORA, MODEL_DEEP, MODEL_FAST, _api_key,
                         looks_like_frontmatter, retrieve_evidence)

# stage → (model, max_tokens) per depth. None means the stage is skipped.
STAGE_PLAN = {
    "understand": {"intro": (MODEL_FAST, 600),  "intermediate": (MODEL_FAST, 600),
                   "advanced": (MODEL_FAST, 800)},
    "evidence":   {"intro": None,               "intermediate": (MODEL_FAST, 1500),
                   "advanced": (MODEL_FAST, 2500)},
    "reasoning":  {"intro": None,               "intermediate": (MODEL_FAST, 4000),
                   "advanced": (MODEL_DEEP, 12000)},
    "professor":  {"intro": (MODEL_FAST, 5000), "intermediate": (MODEL_FAST, 10000),
                   "advanced": (MODEL_DEEP, 16000)},
    "validation": {"intro": None,               "intermediate": (MODEL_FAST, 1200),
                   "advanced": (MODEL_FAST, 1800)},
}


def plan_for(stage: str, depth: str):
    return STAGE_PLAN.get(stage, {}).get(depth, STAGE_PLAN.get(stage, {}).get("intermediate"))


# ── shared LLM helper ─────────────────────────────────────────────────────

class Budget:
    """Tracks what the run actually spent, so the cost claim is measured."""

    def __init__(self):
        self.calls, self.prompt, self.completion, self.reasoning = 0, 0, 0, 0
        self.by_stage: dict[str, dict] = {}

    def record(self, stage, model, usage, secs):
        self.calls += 1
        p = getattr(usage, "prompt_tokens", 0) or 0
        c = getattr(usage, "completion_tokens", 0) or 0
        r = getattr(getattr(usage, "completion_tokens_details", None),
                    "reasoning_tokens", 0) or 0
        self.prompt += p; self.completion += c; self.reasoning += r
        self.by_stage[stage] = {"model": model, "prompt": p, "completion": c,
                                "reasoning": r, "secs": round(secs, 1)}

    def summary(self):
        return {"llm_calls": self.calls, "prompt_tokens": self.prompt,
                "completion_tokens": self.completion,
                "reasoning_tokens": self.reasoning,
                "total_tokens": self.prompt + self.completion,
                "by_stage": self.by_stage}


def _call(client, stage, depth, system, user, budget, force=None):
    """One model call, with an automatic retry when the budget is swallowed.

    deepseek-v4 reasons before answering and those tokens count against
    max_tokens, so a budget sized for the prose alone can be consumed entirely
    by the reasoning chain and return empty content with finish_reason
    "length". This has now bitten three separate stages — the observed case
    here was a survey call reporting completion=3000, reasoning=3000, content
    length 0 on a 14k-character prompt.

    Retrying once with double the room is far cheaper than losing the run, and
    putting it here means every stage inherits the guard instead of each one
    rediscovering the failure.
    """
    spec = force or plan_for(stage, depth)
    if spec is None:
        return ""
    model, max_tokens = spec

    def once(limit):
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=model, max_tokens=limit,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        budget.record(stage, model, resp.usage, time.monotonic() - t0)
        return (resp.choices[0].message.content or "").strip(), resp

    text, resp = once(max_tokens)
    if not text:
        finish = getattr(resp.choices[0], "finish_reason", "")
        used = getattr(getattr(resp.usage, "completion_tokens_details", None),
                       "reasoning_tokens", 0) or 0
        budget.by_stage.setdefault(stage, {})["retried"] = (
            f"empty at {max_tokens} tokens (finish={finish}, reasoning={used})")
        text, _ = once(max_tokens * 2)
    return text


def _json_from(text: str, fallback: dict) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return fallback
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return fallback


# ── stage 2: question understanding ───────────────────────────────────────

_UNDERSTAND_SYS = """You classify a question for a retrieval pipeline. Reply \
with ONLY a JSON object, no prose:

{"intent":"explain|compare|how_to|evaluate|compute|current_events",
 "topics":["3-6 key technical terms to search on"],
 "needs_current":true|false,   // true only if the answer depends on recent
                               // events, releases, prices or "latest/today"
 "needs_compute":true|false,   // true only if a concrete numeric calculation
                               // is required to answer
 "compute_expression":"a single arithmetic expression, or empty",
 "restate":"one sentence restating what is actually being asked"}"""


def understand(question, depth, client, budget):
    raw = _call(client, "understand", depth, _UNDERSTAND_SYS,
                f"QUESTION: {question}", budget)
    u = _json_from(raw, {})
    words = re.findall(r"[a-z0-9][a-z0-9\-]{2,}", question.lower())
    return {
        "intent": u.get("intent", "explain"),
        "topics": u.get("topics") or words[:6],
        "needs_current": bool(u.get("needs_current")),
        "needs_compute": bool(u.get("needs_compute")),
        "compute_expression": (u.get("compute_expression") or "").strip(),
        "restate": u.get("restate") or question,
    }


# ── stage 3: intelligent router ───────────────────────────────────────────

def route(understanding, depth):
    """Deterministic on purpose: routing is a policy decision, and spending a
    model call to re-derive a rule the code already knows is the kind of token
    waste this design is trying to avoid."""
    books = True                                  # the library is always the spine
    web = bool(understanding["needs_current"]) and depth != "intro"
    tools = bool(understanding["needs_compute"]) and depth != "intro"
    why = []
    why.append("books: always — the library is the primary source")
    why.append("web: " + ("question depends on current information"
                          if web else
                          "skipped — intro depth" if understanding["needs_current"]
                          else "not needed — no time-sensitive element"))
    why.append("tools: " + ("a concrete calculation is required"
                            if tools else
                            "skipped — intro depth" if understanding["needs_compute"]
                            else "not needed — nothing to compute"))
    return {"books": books, "web": web, "tools": tools, "why": why}


def _should_escalate_web(routing: dict, book_ev: dict, depth: str) -> bool:
    """route() decides whether to query the web before retrieval ever runs,
    from an LLM's guess about whether the *question* sounds time-sensitive --
    it cannot know whether the *library* actually had anything. When books
    come back completely empty (including when retrieve_evidence() itself
    failed -- missing index, import error -- which never sets
    evidence_strength at all, hence checking `kept` directly rather than
    evidence_strength == "none"), a keyless Wikipedia lookup is a strictly
    better fallback than answering from bare parametric knowledge. Confined to
    the "books came back empty" branch and skipped at intro depth to match
    route()'s own web-skip convention, so this never adds latency to the
    common case where books already have evidence."""
    return not routing["web"] and not book_ev.get("kept") and depth != "intro"


def _mark_web_escalated(routing: dict) -> dict:
    """Rewrite the routing trace after an escalation fires, so the 'why' the
    user sees matches what actually happened -- the original web:false
    reasoning ('not needed', 'skipped — intro depth') is no longer true."""
    routing["web"] = True
    routing["why"] = [w if not w.startswith("web:") else
                      "web: escalated — book search returned nothing"
                      for w in routing["why"]]
    return routing


# ── stage 4c: tools (safe arithmetic, no eval) ────────────────────────────

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {k: getattr(math, k) for k in
          ("sqrt log log2 log10 exp sin cos tan asin acos atan sinh cosh tanh "
           "floor ceil fabs factorial degrees radians").split()}
_FUNCS.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_calc(expr: str):
    """Evaluate arithmetic without eval().

    The existing tool_registry._calculate falls through to eval() — its regex
    guard is `if not allowed.match(...): pass`, which does nothing — so an
    LLM-authored expression would run as code. This walks the AST and permits
    only numbers, arithmetic operators and a fixed list of math functions.
    """
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("only numeric literals are allowed")
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"unsupported expression element: {type(node).__name__}")
    try:
        return {"ok": True, "expression": expr,
                "result": ev(ast.parse(expr, mode="eval"))}
    except Exception as exc:
        return {"ok": False, "expression": expr, "error": str(exc)}


# ── stage 4b: web ─────────────────────────────────────────────────────────

def _http_json(url: str, timeout: int = 12) -> dict:
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "AIBrain/1.0 (personal research tool)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def web_search(query: str, n: int = 3) -> dict:
    """Reference lookup via the Wikipedia API.

    This branch used to scrape html.duckduckgo.com. That endpoint now answers
    HTTP 202 with an anti-bot page containing no result markup at all, so the
    branch was silently returning zero hits while the router still reported
    "web" as consulted — worse than not having it. Wikipedia's API is keyless,
    stable and permits this use.

    Honest limitation: this is a *reference* source, not a live news feed. It
    is good for "what is X" and established background, and will not know
    yesterday's release. Genuine current-events coverage needs a search API
    key (Tavily, Brave, Serp); until one is configured the router's
    needs_current signal is served by encyclopaedic background only.
    """
    import urllib.parse
    try:
        s = _http_json("https://en.wikipedia.org/w/api.php?action=query&list=search"
                       "&format=json&srlimit=%d&srsearch=%s" % (n, urllib.parse.quote(query)))
        titles = [h["title"] for h in s.get("query", {}).get("search", [])][:n]
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "hits": [],
                "source": "wikipedia"}

    hits = []
    for t in titles:
        try:
            sm = _http_json("https://en.wikipedia.org/api/rest_v1/page/summary/"
                            + urllib.parse.quote(t.replace(" ", "_")))
            extract = (sm.get("extract") or "").strip()
            if extract:
                hits.append({"title": t, "snippet": extract[:900],
                             "url": (sm.get("content_urls", {}).get("desktop", {}) or {}).get("page", "")})
        except Exception:
            continue
    return {"ok": True, "hits": hits, "source": "wikipedia",
            "note": "reference background, not live news"}


# ── stage 5: evidence engine ──────────────────────────────────────────────

_EVIDENCE_SYS = """You are the evidence stage of a pipeline. You do NOT answer \
the question. Assess the material and reply with ONLY JSON:

{"usable":["S1","S3"],            // tags that genuinely bear on the question
 "off_topic":["S2"],              // retrieved but not actually relevant
 "agreements":["what two or more sources independently support"],
 "conflicts":["where sources disagree, naming the tags"],
 "gaps":["what the question needs that no source provides"],
 "confidence":"high|medium|low"}

Be strict: a source that merely shares vocabulary is off_topic."""


def evidence_engine(question, book_ev, web_res, tool_res, depth, client, budget):
    if plan_for("evidence", depth) is None:
        return {"skipped": True, "reason": "intro depth — evidence stage skipped to save tokens",
                "usable": [c["tag"] for c in book_ev.get("kept", [])],
                "off_topic": [], "agreements": [], "conflicts": [], "gaps": [],
                "confidence": "unassessed"}
    parts = []
    for c in book_ev.get("kept", []):
        parts.append(f"[{c['tag']}] BOOK · {c['source']} · {c['shelf']} shelf\n{c['text'][:900]}")
    for i, h in enumerate(web_res.get("hits", []), 1):
        parts.append(f"[W{i}] WEB · {h['title']}\n{h['snippet']}")
    if tool_res and tool_res.get("ok"):
        parts.append(f"[T1] TOOL · computed {tool_res['expression']} = {tool_res['result']}")
    if not parts:
        return {"skipped": False, "usable": [], "off_topic": [], "agreements": [],
                "conflicts": [], "gaps": ["no sources were retrieved at all"],
                "confidence": "low"}
    raw = _call(client, "evidence", depth, _EVIDENCE_SYS,
                f"QUESTION: {question}\n\nMATERIAL:\n" + "\n\n".join(parts), budget)
    out = _json_from(raw, {})
    out.setdefault("usable", [c["tag"] for c in book_ev.get("kept", [])])
    for k in ("off_topic", "agreements", "conflicts", "gaps"):
        out.setdefault(k, [])
    out.setdefault("confidence", "medium")
    out["skipped"] = False
    return out


# ── stage 6: reasoning engine ─────────────────────────────────────────────

_REASON_SYS = """You are the reasoning stage. Do NOT write the final answer and \
do not address the reader. Produce a tight analytical skeleton the teaching \
stage will expand:

- the core mechanism or argument, in logical order
- which evidence tag supports each step, or "unsupported" where none does
- the subtlety or failure mode a careful reader should notice
- anything the evidence cannot settle

Be terse. Bullets, not prose."""


def reasoning_engine(question, understanding, book_ev, web_res, tool_res,
                     assessment, depth, client, budget):
    if plan_for("reasoning", depth) is None:
        return {"skipped": True,
                "reason": "intro depth — reasoning folded into the teaching stage",
                "text": ""}
    # Mirrors evidence_engine's own empty-input guard (above): with nothing
    # retrieved, this stage would be sent "SOURCES:\n(none)" and asked which
    # evidence tag supports each step of a skeleton professor_engine then
    # expands — work that's not just wasted, it risks priming the final
    # answer to sound structured about material that doesn't exist. This is
    # also the call that turned the empty-grounding case into the observed
    # 91s/12,702-token/4-call outlier: evidence_engine already self-skips
    # here, so removing this one too drops the worst case to 3 calls.
    if not book_ev.get("kept") and not web_res.get("hits") and not (tool_res and tool_res.get("ok")):
        return {"skipped": True,
                "reason": "no book, web or tool evidence — nothing to build a reasoning skeleton from",
                "text": ""}
    src = "\n\n".join(
        [f"[{c['tag']}] {c['source']}\n{c['text'][:900]}" for c in book_ev.get("kept", [])] +
        [f"[W{i}] {h['title']}: {h['snippet']}" for i, h in enumerate(web_res.get("hits", []), 1)] +
        ([f"[T1] {tool_res['expression']} = {tool_res['result']}"]
         if tool_res and tool_res.get("ok") else []))
    text = _call(client, "reasoning", depth, _REASON_SYS,
                 f"QUESTION: {question}\nRESTATED: {understanding['restate']}\n\n"
                 f"EVIDENCE ASSESSMENT: usable={assessment.get('usable')} "
                 f"conflicts={assessment.get('conflicts')} gaps={assessment.get('gaps')}\n\n"
                 f"SOURCES:\n{src or '(none)'}", budget)
    return {"skipped": False, "text": text}


# ── stage 7: professor engine ─────────────────────────────────────────────

MODE_DIRECTIVE = {
    "explain": "Give a ground-up explanation: intuition first, then the formal "
               "statement. Lead with the idea, not the notation.",
    "socratic": "Teach by guided questioning — 3-5 questions in sequence, each "
                "answerable from the last, without stating the conclusion up front.",
    "exercise": "Pose one concrete worked problem, solve it step by step showing "
                "the reasoning, then state the principle it illustrates.",
    "compare": "Structure the whole answer as a comparison across shared "
               "dimensions, closing with when each option applies.",
}
DEPTH_DIRECTIVE = {
    "intro": "Assume a capable engineer new to this topic. Minimal notation, "
             "concrete examples.",
    "intermediate": "Assume a working practitioner comfortable with Python, "
                    "linear algebra and probability.",
    "advanced": "Assume research-level fluency. Full notation, derive rather "
                "than sketch, engage with failure modes.",
}

_PROF_SYS = """You are the reader's own tutor across machine learning, \
mathematics, robotics, vision, electronics and software. Build the intuition \
first, then formalise it. Teach, synthesise, and where the question invites \
it, recommend a path forward.

Cite inline by tag — [C:topic-id] a curriculum topic, [S#] a book from their \
library, [W#] web, [T1] a computed value. Never invent a tag that was not \
supplied.

The [C:] curriculum topics are real material, not a fallback. Their concepts \
and equations are yours to build on and connect, and on a machine without the \
book indexes they may be all you have — that is not a reason to hedge.

NEVER state a numeric result of your own when a [T] tool value exists — refer \
to the computed value in words rather than restating the digits.

Answer the question. Lead with the substance, never with an apology or an \
inventory of what you lack. The reader came for the idea and how it connects, \
not for a report on your retrieval. Sourcing is shown by your tags, so it \
needs no preamble.

Reason across the sources you were given rather than summarising them one by \
one — joining two things the library treats separately is exactly the work \
expected here. Going beyond the sources is welcome; just never imply a source \
backs a claim it does not.

When something genuinely falls outside everything supplied, note it in one \
short clause at the point where it arises — "the retrieved passages do not \
cover this, so the following is general knowledge" — and carry on. Never open \
with it, never dwell on it, and never let it displace the explanation. Use \
LaTeX for mathematics."""


def professor_engine(question, understanding, book_ev, web_res, tool_res,
                     assessment, reasoning, mode, depth, client, budget,
                     topics=()):
    # Curriculum first. On a host with no book indexes these are the only
    # sources there are, and they are real material — not a fallback apology.
    src_parts = ([CUR.curriculum_block(list(topics))] if topics else [])
    src_parts += [f"[{c['tag']}] ({c['source']} — {c['shelf']} shelf)\n{c['text'][:1100]}"
                  for c in book_ev.get("kept", [])]
    src_parts += [f"[W{i}] ({h['title']})\n{h['snippet']}"
                  for i, h in enumerate(web_res.get("hits", []), 1)]
    if tool_res and tool_res.get("ok"):
        src_parts.append(f"[T1] computed: {tool_res['expression']} = {tool_res['result']}")
    src = "\n\n".join(src_parts) or "(no sources — say so, then answer from general knowledge)"

    extra = ""
    if not assessment.get("skipped"):
        extra = (f"\nEVIDENCE NOTES: off-topic={assessment.get('off_topic')} · "
                 f"conflicts={assessment.get('conflicts')} · gaps={assessment.get('gaps')} · "
                 f"confidence={assessment.get('confidence')}")
    if reasoning.get("text"):
        extra += f"\n\nREASONING SKELETON (expand this, do not repeat it verbatim):\n{reasoning['text']}"

    return _call(client, "professor", depth, _PROF_SYS,
                 f"QUESTION: {question}\n\n"
                 f"HOW TO ANSWER: {MODE_DIRECTIVE.get(mode, MODE_DIRECTIVE['explain'])}\n"
                 f"WHO YOU ARE ANSWERING: {DEPTH_DIRECTIVE.get(depth, DEPTH_DIRECTIVE['intermediate'])}"
                 f"{extra}\n\nSOURCES:\n{src}\n\nWrite the answer now.", budget)


# ── stage 8: validation ───────────────────────────────────────────────────

_VALIDATE_SYS = """You are the validation stage. Check the ANSWER against the \
SOURCES and reply with ONLY JSON:

{"unsupported_claims":["specific claims presented as fact that no source backs"],
 "contradicts_sources":["claims that conflict with a source, naming the tag"],
 "restated_computed_numbers":["any figure the answer states that should have
   come from [T1] but was written out instead — include rounded or
   spelled-out restatements, not just exact digits"],
 "verdict":"pass|caution|fail",
 "note":"one sentence for the reader, or empty"}

Judge only sourcing and consistency. Do not rewrite or critique style.

Judge sourcing honesty, not coverage. Content the answer itself flags as
unsupported, or openly attributes to general knowledge, is CORRECT behaviour
and must not lower the verdict.

A retrieved passage is an EXCERPT, not the whole of what a source says.
Standard development of material the excerpt raises — deriving a stated
result, working a standard example, explaining a named concept in depth — is
expected elaboration, not an unsupported claim. Teaching requires saying far
more than an excerpt contains. Only call something unsupported when it belongs
to none of the supplied material AND is presented as if it came from it.

Do not expect a citation on every sentence. Prose that develops an
already-cited point needs no tag of its own; demanding one would make ordinary
exposition look dishonest.

Reserve "fail" for claims presented as sourced that are not, for contradictions
of a supplied source, or for restating a computed number instead of referring
to it. If the only issue is that the answer says more than the excerpts do,
that is "pass"."""


def validation(question, prose, book_ev, web_res, tool_res, depth, client, budget,
               topics=()):
    """Structural checks always run; the semantic pass is depth-gated."""
    offered = {c["tag"] for c in book_ev.get("kept", [])}
    offered |= {f"W{i}" for i in range(1, len(web_res.get("hits", [])) + 1)}
    offered |= {f"C:{t.id}" for t in topics}
    if tool_res and tool_res.get("ok"):
        offered.add("T1")
    # [C:topic-id] has to be in the pattern or every curriculum citation reads
    # as uncited prose and none of them count toward "cited".
    cited = set(re.findall(r"\[((?:C:[\w\-]+)|(?:[SWT]\d+))\]", prose))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", prose) if len(s.strip()) > 40]
    structural = {
        "cited": sorted(cited), "offered": sorted(offered),
        "fabricated_tags": sorted(cited - offered),
        "unused_sources": sorted(offered - cited),
        "sentences": len(sentences),
        "uncited_sentences": sum(1 for s in sentences if not re.search(r"\[[A-Z]", s)),
    }
    if plan_for("validation", depth) is None:
        structural.update(verdict="pass" if not structural["fabricated_tags"] else "caution",
                          semantic_skipped=True,
                          note="intro depth — structural checks only")
        return structural

    # [T1] is offered as a citable tag above, so the validator has to be shown
    # it too. Without this it looked for the tool result, failed to find it,
    # and reported a correctly-cited computed value as an unsupported claim —
    # the same shape of bug as a source being citable but invisible.
    src = "\n\n".join(
        ([CUR.curriculum_block(list(topics))] if topics else []) +
        [f"[{c['tag']}] {c['text'][:700]}" for c in book_ev.get("kept", [])] +
        [f"[W{i}] {h['snippet']}" for i, h in enumerate(web_res.get("hits", []), 1)] +
        ([f"[T1] {tool_res.get('result')}"] if tool_res and tool_res.get("ok") else []))
    raw = _call(client, "validation", depth, _VALIDATE_SYS,
                f"QUESTION: {question}\n\nSOURCES:\n{src or '(none)'}\n\n"
                f"ANSWER:\n{prose[:6000]}", budget)
    sem = _json_from(raw, {"verdict": "pass", "note": "", "unsupported_claims": [],
                           "contradicts_sources": []})
    structural.update(semantic_skipped=False,
                      unsupported_claims=sem.get("unsupported_claims", []),
                      contradicts_sources=sem.get("contradicts_sources", []),
                      restated_computed_numbers=sem.get("restated_computed_numbers", []),
                      note=sem.get("note", ""),
                      verdict=("caution" if structural["fabricated_tags"]
                               else sem.get("verdict", "pass")))
    return structural


# ── the pipeline ──────────────────────────────────────────────────────────

def run(question: str, mode: str = "explain",
        depth: str = "intermediate") -> Iterator[tuple[str, dict]]:
    question = (question or "").strip()
    if not question:
        yield "error", {"message": "empty question"}
        return
    key = _api_key()
    if not key:
        yield "error", {"message": "No DEEPSEEK_API_KEY found"}
        return
    try:
        from openai import OpenAI
    except ImportError:
        yield "error", {"message": "pip3 install openai"}
        return

    client = OpenAI(api_key=key, base_url="https://api.deepseek.com",
                    timeout=300.0, max_retries=1)
    budget = Budget()
    t_start = time.monotonic()

    # 2 ── understand
    yield "understand", {"msg": "Reading the question…"}
    u = understand(question, depth, client, budget)
    yield "understand", {"msg": f"{u['intent']} · {', '.join(u['topics'][:4])}",
                         "understanding": u}

    # 2b ── curriculum: which topics does this question touch?
    # Matched from the question plus the terms the understanding stage pulled
    # out, so a question that names a concept obliquely still lands.
    topics = CUR.match_topics(question + " " + " ".join(u["topics"][:6]), k=4)

    # 3 ── route
    r = route(u, depth)
    picked = [k for k in ("books", "web", "tools") if r[k]]
    yield "route", {"msg": " + ".join(picked) or "books", "routing": r}

    # 4 ── gather, in parallel
    yield "gather", {"msg": f"Querying {len(picked)} source(s)…"}
    t0 = time.monotonic()
    book_ev, web_res, tool_res = {"kept": [], "rejected": [], "available": False}, {"hits": []}, None
    query = question + " " + " ".join(u["topics"][:4])
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_books = pool.submit(retrieve_evidence, query) if r["books"] else None
        f_web = pool.submit(web_search, question) if r["web"] else None
        if r["tools"] and u["compute_expression"]:
            tool_res = safe_calc(u["compute_expression"])
        if f_books:
            book_ev = f_books.result()
        if f_web:
            web_res = f_web.result()

    # Retrieval-informed escalation: route() couldn't know whether the
    # library would actually have anything — now that retrieval has run, we
    # do, and can fall back to a keyless web reference rather than leaving
    # the answer with nothing but the model's own parametric knowledge.
    if _should_escalate_web(r, book_ev, depth):
        web_res = web_search(question)
        _mark_web_escalated(r)

    gathered = (f"{len(topics)} curriculum topic(s), "
                f"{len(book_ev.get('kept', []))} book passage(s)"
                + (f", {len(web_res.get('hits', []))} web result(s)" if r["web"] else "")
                + (", 1 computed value" if tool_res and tool_res.get("ok") else ""))
    yield "gather", {"msg": f"{gathered} · {int((time.monotonic()-t0)*1000)}ms",
                     "evidence": book_ev, "web": web_res, "tool": tool_res,
                     "topics": [{"id": t.id, "title": t.title, "level": t.level}
                                for t in topics]}

    # 5 ── evidence engine
    yield "evidence", {"msg": "Verifying and comparing sources…"}
    assessment = evidence_engine(question, book_ev, web_res, tool_res, depth, client, budget)
    yield "evidence", {"msg": ("skipped (intro depth)" if assessment.get("skipped") else
                               f"{len(assessment.get('usable', []))} usable · "
                               f"{len(assessment.get('conflicts', []))} conflict(s) · "
                               f"confidence {assessment.get('confidence')}"),
                       "assessment": assessment}

    # 6 ── reasoning
    yield "reasoning", {"msg": "Building the argument…"}
    reasoning = reasoning_engine(question, u, book_ev, web_res, tool_res,
                                 assessment, depth, client, budget)
    yield "reasoning", {"msg": (reasoning["reason"] if reasoning.get("skipped")
                                else f"{len(reasoning['text'].split())} words of skeleton"),
                        "reasoning": reasoning}

    # 7 ── professor, with heartbeats so the stream never goes silent
    box: dict = {}

    def _teach():
        try:
            box["prose"] = professor_engine(question, u, book_ev, web_res, tool_res,
                                            assessment, reasoning, mode, depth,
                                            client, budget, topics)
        except Exception as exc:
            box["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=_teach, daemon=True)
    t_prof = time.monotonic()
    yield "professor", {"msg": "Teaching…", "elapsed_s": 0}
    worker.start()
    while worker.is_alive():
        worker.join(timeout=5.0)
        if worker.is_alive():
            yield "professor", {"msg": f"Teaching… {int(time.monotonic()-t_prof)}s",
                                "elapsed_s": int(time.monotonic() - t_prof)}
    if box.get("error"):
        yield "error", {"message": box["error"]}
        return
    prose = (box.get("prose") or "").strip()
    if not prose:
        yield "error", {"message": "the teaching stage returned nothing"}
        return
    yield "professor", {"msg": f"Taught in {int(time.monotonic()-t_prof)}s",
                        "elapsed_s": int(time.monotonic() - t_prof)}

    # 8 ── validation
    yield "validation", {"msg": "Checking the answer against its sources…"}
    checks = validation(question, prose, book_ev, web_res, tool_res, depth, client,
                        budget, topics)
    # Report what was cited, not how many sentences went untagged. A ratio like
    # "43/55 uncited" sitting next to the verdict reads as an accusation, when a
    # long explanation resting on a handful of sources is what good teaching
    # looks like. The count stays in the payload for the evidence panel.
    yield "validation", {"msg": (f"{checks['verdict']} · {len(checks['cited'])} "
                                 f"source{'' if len(checks['cited']) == 1 else 's'} cited"
                                 + (f" · {len(checks['fabricated_tags'])} fabricated tag(s)"
                                    if checks["fabricated_tags"] else "")),
                         "validation": checks}

    # 9 ── answer
    yield "done", {
        "question": question, "mode": mode, "depth": depth,
        "prose": prose, "understanding": u, "routing": r,
        "evidence": book_ev, "web": web_res, "tool": tool_res,
        "topics": [{"id": t.id, "title": t.title, "level": t.level} for t in topics],
        "assessment": assessment, "reasoning": reasoning, "validation": checks,
        "budget": budget.summary(),
        "elapsed_s": int(time.monotonic() - t_start),
        "honesty": {
            "grounded_in_library": bool(book_ev.get("kept")),
            "covered_by_curriculum": bool(topics),
            "shelves_searched": len(book_ev.get("searched", [])),
            "used_web": bool(web_res.get("hits")),
            "used_tools": bool(tool_res and tool_res.get("ok")),
            "note": ("Tags: [C:] curriculum, [S] your books, [W] web, "
                     "[T] a computed value. Untagged sentences are the "
                     "model's own synthesis."),
        },
    }


def answer(question: str, mode: str = "explain", depth: str = "intermediate") -> dict:
    last: dict = {}
    for stage, payload in run(question, mode, depth):
        if stage in ("done", "error"):
            last = {"stage": stage, **payload}
    return last
