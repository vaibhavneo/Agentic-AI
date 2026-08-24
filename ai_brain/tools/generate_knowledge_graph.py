"""One-time, offline generation of memory/knowledge_graph.json.

    python3 tools/generate_knowledge_graph.py

NOT part of the served app and never called per-request — this is a batch
job you run by hand, review the output of, and commit (the output lands in
data/, not memory/ — see knowledge_graph.py's KG_PATH comment for why).
It makes a handful
of LLM calls (one per batch of curriculum topics, ~5 total for the current
47 topics) to propose typed edges beyond the `prerequisites` field
curriculum.py already has:

    related_to · part_of · contrasts_with · extends
    used_by · example_of · explained_by · applied_to

Nodes are exactly curriculum.py's existing 47 topic ids — no new topics are
invented here. Every proposed edge is validated before being trusted: the
target must be a real topic id, the relation type must be one of the eight
above, and self-loops are dropped. Malformed or hallucinated entries are
silently dropped (counted and reported), never allowed to crash the run or
poison the output — the same defensive-parsing discipline pipeline.py's
_normalize_conflict()/_json_from() already apply elsewhere in this app.

This does not attempt a perfect ontology. An empty relation list for a
topic is the expected, correct answer when nothing genuinely applies —
never forced.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import curriculum as CUR                              # noqa: E402
from brain_tutor import _api_key, MODEL_FAST           # noqa: E402
from pipeline import _json_from, _call, Budget         # noqa: E402

OUT_PATH = HERE / "data" / "knowledge_graph.json"   # committed to git, not memory/ (see knowledge_graph.py)
RELATION_TYPES = ("related_to", "part_of", "contrasts_with", "extends",
                  "used_by", "example_of", "explained_by", "applied_to")
BATCH_SIZE = 10

# Deliberately terse. An earlier, more elaborate version of this prompt
# (per-type prose definitions with parenthetical examples, a 4-bullet rules
# section, a verbose annotated JSON template) reliably burned its ENTIRE
# token budget on reasoning and returned empty content — confirmed by
# isolating the cause: identical topics/candidates through a short prompt
# succeeded instantly (77 reasoning tokens), the elaborate prompt failed
# even at 20,000 tokens with 0 content, and this terser version (one line
# per type, no rules section, compact JSON example) succeeds reliably at
# full batch scale (~7000 reasoning tokens, real content). Keep it short.
_SYS = """Propose typed edges between AI/ML curriculum topics for a lightweight \
knowledge graph. Types: related_to, part_of, contrasts_with, extends, used_by, \
example_of, explained_by, applied_to. NOT prerequisites (that's separate).

related_to=generally relevant, symmetric. part_of=X is a component of Y. \
contrasts_with=commonly compared, symmetric. extends=X builds on/generalizes Y. \
used_by=X is used as a building block by Y. example_of=X is a specific instance of Y. \
explained_by=understanding X is aided by Y (soft, not a hard prerequisite). \
applied_to=X is applied in the domain of Y.

Only use topic ids from the TOPIC LIST given. Skip a type when nothing genuinely \
fits - empty is correct and expected, don't force edges. Never propose a topic \
edging to itself. Be decisive - do not deliberate over every possible pair.

Reply with ONLY JSON, no prose, no markdown fences:
{"topic-id": {"related_to": ["other-id"], "used_by": ["other-id"], ...only \
non-empty types, one entry per source topic...}}"""


def _batches(topics, size):
    for i in range(0, len(topics), size):
        yield topics[i:i + size]


def _topic_list_block(topics) -> str:
    return "\n".join(f"- {t.id}: {t.title} — {', '.join(t.key_concepts[:5])}"
                     for t in topics)


def validate_batch(parsed: dict, valid_ids: set[str]) -> tuple[dict, dict]:
    """The generator's own validator, isolated so it's testable without a
    real LLM call: given one batch's already-JSON-parsed response and the
    set of real topic ids, return (clean_edges, dropped_counts). Rejects a
    hallucinated node id, an invalid relation-type string, and self-loops —
    never raises on malformed input, matching _normalize_conflict()'s/
    _json_from()'s existing defensive-parsing discipline elsewhere in this
    app: drop what's wrong, keep what's right, never crash the run."""
    edges: dict[str, dict[str, list[str]]] = {}
    dropped = {"bad_source": 0, "bad_target": 0, "bad_type": 0, "self_loop": 0}
    if not isinstance(parsed, dict):
        return edges, dropped
    for source_id, rels in parsed.items():
        if source_id not in valid_ids:
            dropped["bad_source"] += 1
            continue
        if not isinstance(rels, dict):
            continue
        clean: dict[str, list[str]] = {}
        for rel_type, targets in rels.items():
            if rel_type not in RELATION_TYPES:
                dropped["bad_type"] += 1
                continue
            if not isinstance(targets, list):
                continue
            kept = []
            for t in targets:
                if not isinstance(t, str) or t not in valid_ids:
                    dropped["bad_target"] += 1
                    continue
                if t == source_id:
                    dropped["self_loop"] += 1
                    continue
                kept.append(t)
            if kept:
                clean[rel_type] = kept
        if clean:
            edges[source_id] = clean
    return edges, dropped


def generate() -> dict:
    key = _api_key()
    if not key:
        sys.exit("No DEEPSEEK_API_KEY found — see brain_tutor._api_key() for where it looks.")
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com",
                    timeout=180.0, max_retries=1)

    all_topics = list(CUR.TOPICS.values())
    valid_ids = set(CUR.TOPICS.keys())
    all_ids_block = _topic_list_block(all_topics)

    edges: dict[str, dict[str, list[str]]] = {}
    dropped = {"bad_source": 0, "bad_target": 0, "bad_type": 0, "self_loop": 0}
    budget = Budget()
    calls = 0
    empty_responses = 0

    for batch in _batches(all_topics, BATCH_SIZE):
        calls += 1
        batch_ids = ", ".join(t.id for t in batch)
        print(f"[{calls}] proposing edges for: {batch_ids}", file=sys.stderr)
        user = (f"FULL TOPIC LIST (valid edge targets — {len(all_topics)} topics):\n{all_ids_block}\n\n"
               f"SOURCE TOPICS FOR THIS BATCH (propose edges FROM each of these):\n"
               f"{_topic_list_block(batch)}")
        # _call(), not a bare client.chat.completions.create(): deepseek-v4
        # reasons before answering and those tokens count against max_tokens,
        # so a budget sized for the JSON alone can be entirely consumed by
        # reasoning and return empty content with finish_reason "length" —
        # exactly what happened on the first run of this script at
        # max_tokens=4000 (reasoning_tokens=4000, content_length=0). _call()
        # already has the retry-at-2x-budget guard for this; a generous
        # starting budget (10000) plus that guard is more robust than
        # hand-rolling the same retry here a second time.
        raw = _call(client, "kg_batch", "intermediate", _SYS, user, budget,
                   force=(MODEL_FAST, 10000))
        if not raw.strip():
            empty_responses += 1
            print(f"    WARNING: empty response for batch {calls} even after _call()'s "
                 f"built-in retry — skipping this batch, no edges from it", file=sys.stderr)
            continue
        parsed = _json_from(raw, {})

        batch_edges, batch_dropped = validate_batch(parsed, valid_ids)
        edges.update(batch_edges)
        for k in dropped:
            dropped[k] += batch_dropped[k]

    b = budget.summary()
    print(f"\n{calls} batched calls ({empty_responses} came back empty) · "
         f"{len(edges)}/{len(all_topics)} topics got at least one edge · "
         f"dropped (malformed/hallucinated, never trusted): {dropped}\n"
         f"one-time generation spend: {b['llm_calls']} LLM calls, "
         f"{b['total_tokens']} tokens ({b['reasoning_tokens']} reasoning) — "
         f"NOT part of any per-request cost", file=sys.stderr)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL_FAST,
        "relation_types": list(RELATION_TYPES),
        "topic_count": len(all_topics),
        "dropped": dropped,
        "generation_budget": b,
        "edges": edges,
    }


if __name__ == "__main__":
    data = generate()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    n_edges = sum(len(v) for e in data["edges"].values() for v in e.values())
    print(f"wrote {OUT_PATH} — {len(data['edges'])} topics, {n_edges} total edges", file=sys.stderr)
