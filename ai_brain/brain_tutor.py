"""AI Brain: a grounded tutor over the whole personal library.

Same discipline as the Quantum Professor: the provenance of every sentence is
inspectable, the pipeline is streamed so it can be watched rather than
asserted, and the model is told to say when the library does not cover
something instead of quietly filling the gap.

Two differences, both forced by scale rather than taste:

  * There is no curated curriculum to fall back on. In the physics app the 32
    hand-written topics carried an answer when retrieval failed. Here the books
    *are* the product, so "no usable sources" is reported as exactly that.

  * Retrieval is BM25 over on-disk SQLite FTS5 (second_brain/fts.py), not the
    in-memory TF-IDF retriever. At this library's size TF-IDF needed ~9.3 GB of
    RAM and ~5 s per query; FTS5 serves the same content from disk in
    milliseconds. Because a per-corpus query costs ~4 ms, every corpus is
    searched on every question — breadth is cheaper than routing heuristics
    and avoids guessing which shelf holds the answer.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Iterator

BRAIN_ROOT = Path(
    os.getenv("SECOND_BRAIN_ROOT", str(Path(__file__).resolve().parents[1]))
).expanduser()

# The shelves that make up the AI Brain. Everything here is searched on every
# question; see the module docstring for why that is affordable.
BRAIN_CORPORA = [
    "desk-ai", "desk-ai-agents-and-agentic-ai", "desk-ai-research-papers",
    "desk-llms", "desk-generative-ai", "desk-nlp",
    "desk-deep-learning", "desk-machine-learning", "desk-reinforcement-learning",
    "desk-mathematics", "desk-mathematics-for-machine-learning-and-deep-learning",
    "desk-data-science", "desk-computer-vision", "desk-computer-science",
    "desk-python", "desk-robotics", "desk-electronics",
]

PER_CORPUS_K = 3        # candidates pulled from each shelf before global ranking
KEEP_K = 8              # sources actually handed to the model
MIN_RAW_SCORE = 3.0     # BM25 floor; below this a hit is a coincidence of words
MIN_CHUNK_CHARS = 200
WEAK_EVIDENCE = 8.0     # top hit under this ⇒ warn the model its grounding is thin

MODEL_FAST = "deepseek-v4-flash"
MODEL_DEEP = "deepseek-v4-pro"
MODEL_FOR_DEPTH = {"intro": MODEL_FAST, "intermediate": MODEL_FAST,
                   "advanced": MODEL_DEEP}
# Larger than the physics app's budgets on purpose: this prompt carries up to
# eight ~1,200-char sources, and a measured intermediate run exhausted 8,000
# tokens on reasoning, returned empty, and only succeeded on the retry — 157s
# for an answer that should take ~40s. Size for the reasoning, not the prose.
DEPTH_TOKENS = {"intro": 8000, "intermediate": 14000, "advanced": 22000}
LLM_TIMEOUT_S = 300.0


def model_for(depth: str) -> str:
    return MODEL_FOR_DEPTH.get(depth, MODEL_FAST)


def _api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if key:
        return key
    for env in (Path(__file__).parent / ".env",
                BRAIN_ROOT / "learn_agent" / ".env",
                BRAIN_ROOT / ".env"):
        try:
            for line in env.read_text().splitlines():
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return ""


# ── retrieval ─────────────────────────────────────────────────────────────

_DOT_LEADER = re.compile(r"\.{4,}")
_SPACED_OUT = re.compile(r"(?:\b[A-Za-z]\s){6,}")


def looks_like_frontmatter(text: str) -> str | None:
    """Reject contents pages and indexes.

    Good chunking fixed chunk *size*; it did not stop a technical book from
    opening with a table of contents, and such a page is dense in exactly the
    vocabulary a reader asks about, so it ranks far above real prose.
    """
    if not text:
        return "empty"
    if len(_DOT_LEADER.findall(text)) >= 3:
        return "contents page (dot leaders)"
    if len(_SPACED_OUT.findall(text)) >= 2:
        return "broken PDF letter-spacing (front matter)"
    if sum(c.isdigit() for c in text) / max(len(text), 1) > 0.14:
        return "index or contents page (digit-dense)"
    if sum(c.isalpha() for c in text) / max(len(text), 1) < 0.55:
        return "not prose (symbol or number dense)"
    return None


def _shelf(corpus_id: str) -> str:
    return corpus_id.replace("desk-", "").replace("-", " ")


# Ported from second_brain/gateway.py's _shingles/_near_dup — that module is
# wired to the unused in-memory TF-IDF Retriever, not the BM25/FTS5 path this
# app actually queries, so the module itself isn't importable here. The
# algorithm has no dependency on which retriever produced the hits (it only
# looks at text), so it travels on its own.
def _shingles(text: str, n: int = 8) -> set[str]:
    words = text.lower().split()
    return {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def _near_dup(a: str, b: str, threshold: float = 0.8) -> bool:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= threshold


def _filter_and_dedup(scored: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Score/length/frontmatter filter, then near-duplicate collapse.

    Dedup runs *inside* the KEEP_K loop, not after — a near-duplicate must not
    consume a citation slot that a genuinely distinct, lower-ranked passage
    could take instead. `scored` is already sorted best-first, so the first
    copy of a duplicated passage a shelf offers is always the survivor.
    """
    kept: list[dict] = []
    rejected: list[dict] = []
    deduped: list[dict] = []
    for item in scored:
        if len(kept) >= KEEP_K:
            break
        if item["raw_score"] < MIN_RAW_SCORE:
            item["why"] = f"BM25 {item['raw_score']} below floor {MIN_RAW_SCORE}"
            rejected.append(item)
            continue
        if len(item["text"]) < MIN_CHUNK_CHARS:
            item["why"] = "too short to ground on"
            rejected.append(item)
            continue
        if (reason := looks_like_frontmatter(item["text"])):
            item["why"] = reason
            rejected.append(item)
            continue
        dup = next((k for k in kept if _near_dup(item["text"], k["text"])), None)
        if dup:
            dup.setdefault("shelves", [dup["shelf"]])
            dup.setdefault("sources", [dup["source"]])
            if item["shelf"] not in dup["shelves"]:
                dup["shelves"].append(item["shelf"])
            if item["source"] not in dup["sources"]:
                dup["sources"].append(item["source"])
            item["why"] = f"near-duplicate of {dup['tag']}"
            item["merged_into"] = dup["tag"]
            deduped.append(item)
            continue
        item["tag"] = f"S{len(kept) + 1}"
        kept.append(item)
    return kept, rejected, deduped


def retrieve_evidence(question: str) -> dict:
    """BM25 across every shelf, then keep the globally best few."""
    if str(BRAIN_ROOT) not in sys.path:
        sys.path.insert(0, str(BRAIN_ROOT))
    try:
        from second_brain import fts
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}",
                "kept": [], "rejected": [], "searched": [], "missing": []}

    hits, searched, missing = [], [], []
    for cid in BRAIN_CORPORA:
        if not fts.db_path(cid).exists():
            missing.append(cid)
            continue
        searched.append(cid)
        try:
            hits.extend(fts.search(cid, question, top_k=PER_CORPUS_K))
        except Exception:
            continue                       # one bad shelf must not sink the answer

    if not searched:
        return {"available": False,
                "reason": "no shelf has a search index yet — run second_brain/fts.py",
                "kept": [], "rejected": [], "searched": [], "missing": missing}

    scored = [{
        "text": (h.get("text") or "").strip(),
        "source": Path(str(h.get("source", "?"))).name,
        "shelf": _shelf((h.get("corpus") or ["?"])[0]),
        "raw_score": h.get("raw_score", 0.0),
        # Nullable, additive (Milestone 2): only shelves re-ingested since the
        # metadata schema landed carry real values here — fts.search() itself
        # already returns None for any shelf still on the old schema, so this
        # is a pure passthrough, no new filtering or ranking behavior.
        "author": h.get("author"),
        "title": h.get("title"),
        "chapter": h.get("chapter"),
        "page_start": h.get("page_start"),
        "page_end": h.get("page_end"),
    } for h in hits]
    scored.sort(key=lambda c: -c["raw_score"])

    kept, rejected, deduped = _filter_and_dedup(scored)

    top = kept[0]["raw_score"] if kept else 0.0
    return {"available": True, "kept": kept, "rejected": rejected[:6],
            "deduped": deduped[:6],
            "searched": searched, "missing": missing,
            "shelves_hit": sorted({c["shelf"] for c in kept}),
            "top_score": top,
            "evidence_strength": ("none" if not kept
                                  else "weak" if top < WEAK_EVIDENCE else "usable"),
            "scoring_note": ("BM25 over on-disk FTS5, higher is better. Each shelf "
                             f"offers its best {PER_CORPUS_K}; the globally top "
                             f"{KEEP_K} survive filtering, near-duplicates "
                             "collapsed into one citation.")}


# ── pedagogy ──────────────────────────────────────────────────────────────

MODE_DIRECTIVE = {
    "explain": "Give a ground-up explanation. Build the intuition first, then "
               "formalise. Lead with the idea, not the notation.",
    "socratic": "Teach by guided questioning. Ask 3-5 short questions in sequence "
                "that lead the reader to the answer, giving just enough after each "
                "to make the next answerable. Do not state the conclusion up front.",
    "exercise": "Practice-first. Pose one concrete worked problem, walk through it "
                "step by step showing the reasoning, then state the general "
                "principle it illustrates.",
    "compare": "Structure the answer as a comparison: name what is being "
               "contrasted, treat each across the same dimensions, and close with "
               "when each applies.",
}
DEPTH_DIRECTIVE = {
    "intro": "Assume a capable engineer who is new to this topic. Avoid heavy "
             "notation; use concrete examples and analogies.",
    "intermediate": "Assume a working practitioner: comfortable with Python, basic "
                    "linear algebra and probability. Standard notation is fine.",
    "advanced": "Assume research-level fluency. Use full notation, derive rather "
                "than sketch, and engage with the subtleties and failure modes.",
}

_SYSTEM = """You are the reader's own technical tutor, answering from their \
personal library. You are one stage of a pipeline that shows exactly where each \
part of the answer came from, so honesty about sourcing matters more than \
sounding complete.

Ground the explanation in the SOURCES and cite them inline as [S1], [S2]. Where \
you go beyond them — background, connective tissue, your own synthesis — that is \
welcome, but do not imply a source supports a claim it does not. If the sources \
are off-topic or thin, open with one short sentence saying so, then answer from \
general knowledge and make clear that is what you are doing.

Never invent a citation tag that was not supplied. Prefer being useful and \
clearly-sourced over being exhaustive. Use LaTeX for mathematics."""


def _compose(question, evidence, mode, depth, client, token_override=None):
    if evidence.get("kept"):
        src = "\n\n".join(
            f"[{c['tag']}] ({c['source']} — {c['shelf']} shelf, BM25 {c['raw_score']})\n"
            f"{c['text'][:1200]}" for c in evidence["kept"])
        if evidence.get("evidence_strength") == "weak":
            src += (f"\n\nNOTE: the best of these scored only {evidence.get('top_score')} — "
                    "treat them as possibly off-topic and say so if they are.")
    else:
        src = ("(nothing in the library matched this question — say so in one "
               "sentence, then answer from general knowledge)")

    user = (f"QUESTION: {question}\n\n"
            f"HOW TO ANSWER: {MODE_DIRECTIVE.get(mode, MODE_DIRECTIVE['explain'])}\n"
            f"WHO YOU ARE ANSWERING: {DEPTH_DIRECTIVE.get(depth, DEPTH_DIRECTIVE['intermediate'])}\n\n"
            f"SOURCES FROM THE READER'S LIBRARY:\n{src}\n\nWrite the answer now.")

    resp = client.chat.completions.create(
        model=model_for(depth),
        max_tokens=token_override or DEPTH_TOKENS.get(depth, 8000),
        messages=[{"role": "system", "content": _SYSTEM},
                  {"role": "user", "content": user}],
    )
    return resp.choices[0].message.content or ""


def _audit(prose: str, evidence: dict) -> dict:
    cited = set(re.findall(r"\[(S\d+)\]", prose))
    offered = {c["tag"] for c in evidence.get("kept", [])}
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", prose) if len(s.strip()) > 40]
    return {
        "cited": sorted(cited), "offered": sorted(offered),
        "hallucinated_tags": sorted(cited - offered),
        "unused_sources": sorted(offered - cited),
        "sentences": len(sentences),
        "uncited_sentences": sum(1 for s in sentences if not re.search(r"\[S\d+\]", s)),
    }


# ── the pipeline ──────────────────────────────────────────────────────────

def answer_stream(question: str, mode: str = "explain",
                  depth: str = "intermediate") -> Iterator[tuple[str, dict]]:
    question = (question or "").strip()
    if not question:
        yield "error", {"message": "empty question"}
        return

    yield "retrieve", {"msg": f"Searching {len(BRAIN_CORPORA)} shelves…"}
    t_r = time.monotonic()
    evidence = retrieve_evidence(question)
    took = int((time.monotonic() - t_r) * 1000)
    if not evidence["available"]:
        yield "retrieve", {"msg": f"Library unavailable — {evidence['reason']}",
                           "evidence": evidence}
    else:
        yield "retrieve", {
            "msg": (f"{len(evidence['kept'])} source(s) from "
                    f"{len(evidence['shelves_hit'])} shelf/shelves, "
                    f"{len(evidence['rejected'])} rejected · {took}ms"),
            "evidence": evidence}

    key = _api_key()
    if not key:
        yield "error", {"message": "No DEEPSEEK_API_KEY found"}
        return
    try:
        from openai import OpenAI
    except ImportError:
        yield "error", {"message": "pip3 install openai"}
        return

    chosen = model_for(depth)
    yield "adapt", {"msg": f"{mode} · {depth} · {chosen}",
                    "mode": mode, "depth": depth, "model": chosen}

    client = OpenAI(api_key=key, base_url="https://api.deepseek.com",
                    timeout=LLM_TIMEOUT_S, max_retries=1)

    # The model reasons for 30-200s. Without ticks the stream goes silent for
    # that whole stretch: the UI looks hung and an idle connection that long is
    # what an edge proxy drops.
    box: dict = {}

    def _run():
        try:
            p = _compose(question, evidence, mode, depth, client)
            if not p.strip():
                box["retrying"] = True
                p = _compose(question, evidence, mode, depth, client,
                             token_override=DEPTH_TOKENS.get(depth, 8000) * 2)
            box["prose"] = p
        except Exception as exc:
            box["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=_run, daemon=True)
    t0 = time.monotonic()
    yield "compose", {"msg": "Composing the answer…", "elapsed_s": 0}
    worker.start()
    said_retry = False
    while worker.is_alive():
        worker.join(timeout=5.0)
        if not worker.is_alive():
            break
        secs = int(time.monotonic() - t0)
        if box.get("retrying") and not said_retry:
            said_retry = True
            yield "compose", {"msg": "Empty completion — retrying with more room…",
                              "elapsed_s": secs}
        else:
            yield "compose", {"msg": f"Composing the answer… {secs}s", "elapsed_s": secs}

    if box.get("error"):
        yield "error", {"message": box["error"]}
        return
    prose = box.get("prose") or ""
    if not prose.strip():
        yield "error", {"message": "model returned an empty completion twice"}
        return

    total = int(time.monotonic() - t0)
    yield "compose", {"msg": f"Composed in {total}s", "elapsed_s": total}
    yield "done", {
        "question": question, "mode": mode, "depth": depth, "model": chosen,
        "prose": prose, "evidence": evidence, "audit": _audit(prose, evidence),
        "elapsed_s": total,
        "honesty": {
            "grounded_in_library": bool(evidence.get("kept")),
            "shelves_searched": len(evidence.get("searched", [])),
            "shelves_without_index": evidence.get("missing", []),
            "note": ("BM25 relevance, not certainty. Sentences without a [S] tag "
                     "are the model's own synthesis, not something a book said."),
        },
    }


def answer(question: str, mode: str = "explain", depth: str = "intermediate") -> dict:
    last: dict = {}
    for stage, payload in answer_stream(question, mode, depth):
        if stage in ("done", "error"):
            last = {"stage": stage, **payload}
    return last
