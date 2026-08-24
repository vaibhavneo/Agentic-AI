"""A lightweight, typed knowledge graph over curriculum.py's 47 topics.

Nodes are exactly curriculum.py's existing topic ids — no new nodes here.
Edges come from two sources, folded into one bidirectional index at import
time (pure stdlib, no new dependency, no LLM call at query time):

  1. data/knowledge_graph.json — 8 relation types generated once, offline,
     by tools/generate_knowledge_graph.py: related_to, part_of,
     contrasts_with, extends, used_by, example_of, explained_by, applied_to.
     Committed to git (unlike memory/) since it's a reviewed artifact, not
     runtime state — see KG_PATH below for why.
  2. curriculum.TOPICS[*].prerequisites — the existing, hand-authored
     prerequisite field, folded in as a 9th relation type ("prerequisites",
     reverse "enables") so find_path() can walk it without a second,
     parallel prerequisite mechanism ever needing to exist here.

Several relation types are directional (used_by, explained_by, applied_to,
example_of, part_of) — querying from a target node's own side would find
nothing without an explicit reverse edge, so every stored edge is inserted
in both directions at load time, forward under its own label and backward
under its paired reverse label (_REVERSE below).

If memory/knowledge_graph.json doesn't exist yet (the generator hasn't been
run), this module still works — the graph is just the prerequisite edges
curriculum.py already has, nothing crashes.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import curriculum as CUR

# Deliberately NOT under memory/: that directory is gitignored/dockerignored
# runtime state living on the Railway volume (conversation.json, mastery.db,
# research_notebook.json — self-healing, fine to start empty). This file is
# the opposite: a reviewed, one-time-generated artifact that cost real LLM
# spend to produce. It belongs in git and in every Docker build so a fresh
# environment has it immediately, rather than depending on the volume
# having survived and a human remembering to re-run the generator.
KG_PATH = Path(__file__).parent / "data" / "knowledge_graph.json"

RELATION_TYPES = ("related_to", "part_of", "contrasts_with", "extends",
                  "used_by", "example_of", "explained_by", "applied_to")

# Every relation type this module indexes, including the folded-in
# prerequisite pseudo-type, mapped to its reverse label.
_REVERSE = {
    "related_to": "related_to",
    "part_of": "has_part",
    "has_part": "part_of",
    "contrasts_with": "contrasts_with",
    "extends": "extended_by",
    "extended_by": "extends",
    "used_by": "uses",
    "uses": "used_by",
    "example_of": "has_example",
    "has_example": "example_of",
    "explained_by": "explains",
    "explains": "explained_by",
    "applied_to": "has_application",
    "has_application": "applied_to",
    "prerequisites": "enables",
    "enables": "prerequisites",
}


def _load_raw() -> dict:
    try:
        return json.loads(KG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"edges": {}}


def _build_index(raw_edges: dict) -> dict[str, dict[str, set[str]]]:
    idx: dict[str, dict[str, set[str]]] = {}

    def add(a: str, rel: str, b: str) -> None:
        idx.setdefault(a, {}).setdefault(rel, set()).add(b)

    valid = set(CUR.TOPICS.keys())
    for source, rels in raw_edges.items():
        if source not in valid or not isinstance(rels, dict):
            continue
        for rel_type, targets in rels.items():
            if rel_type not in RELATION_TYPES or not isinstance(targets, list):
                continue
            for target in targets:
                if target not in valid or target == source:
                    continue          # defensive: the generator already validates this,
                add(source, rel_type, target)       # but a hand-edited file might not
                add(target, _REVERSE[rel_type], source)

    for topic in CUR.TOPICS.values():
        for prereq in topic.prerequisites:
            if prereq not in valid:
                continue
            add(topic.id, "prerequisites", prereq)
            add(prereq, "enables", topic.id)
    return idx


_RAW = _load_raw()
_INDEX = _build_index(_RAW.get("edges", {}))


def relations(topic_id: str, rel_type: str | None = None) -> list[str]:
    """Neighbor topic ids. With rel_type, only that relation (either an
    original label or its reverse — both are indexed). Without it, every
    neighbor across every indexed relation, including prerequisites/enables."""
    node = _INDEX.get(topic_id, {})
    if rel_type is not None:
        return sorted(node.get(rel_type, ()))
    seen: set[str] = set()
    for targets in node.values():
        seen |= targets
    return sorted(seen)


def find_path(a: str, b: str, rel_types: tuple[str, ...] = ("prerequisites",)) -> list[str] | None:
    """BFS restricted to the given relation types. Returns the path
    (inclusive of a and b) or None if unreachable. The default matches
    learning_path()'s own semantics exactly — walk only the prerequisite
    graph, since a path computed indiscriminately across e.g. contrasts_with
    edges isn't a coherent "path" in any useful sense."""
    if a == b:
        return [a]
    seen = {a}
    q = deque([[a]])
    while q:
        path = q.popleft()
        node = path[-1]
        neighbors: set[str] = set()
        for rt in rel_types:
            neighbors |= _INDEX.get(node, {}).get(rt, set())
        for nxt in sorted(neighbors):
            if nxt == b:
                return path + [nxt]
            if nxt not in seen:
                seen.add(nxt)
                q.append(path + [nxt])
    return None


def explain_edge(a: str, b: str) -> str | None:
    """The first stored edge directly connecting a and b (in either
    direction, since both are indexed), described as 'a --type--> b', or
    None if no direct edge exists."""
    node = _INDEX.get(a, {})
    for rel_type, targets in node.items():
        if b in targets:
            return f"{a} --{rel_type}--> {b}"
    return None


def overlap(a: str, b: str) -> dict:
    """Where two topics' neighborhoods intersect, plus whether they're
    directly connected. 'Where do two concepts overlap' from the spec."""
    shared = sorted(set(relations(a)) & set(relations(b)))
    return {"shared_neighbors": shared, "direct_edge": explain_edge(a, b)}


def stats() -> dict:
    """Generation metadata, for the data-quality checkpoint review — not
    used by any request-serving code path."""
    return {
        "generated_at": _RAW.get("generated_at"),
        "model": _RAW.get("model"),
        "topic_count": _RAW.get("topic_count"),
        "topics_with_edges": len(_RAW.get("edges", {})),
        "dropped_during_generation": _RAW.get("dropped"),
        "total_edges_indexed": sum(len(v) for node in _INDEX.values() for v in node.values()) // 2,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        print(json.dumps(stats(), indent=2))
    elif len(sys.argv) > 2 and sys.argv[1] == "relations":
        for r in relations(sys.argv[2]):
            print(f"  {r}")
    elif len(sys.argv) > 3 and sys.argv[1] == "path":
        print(find_path(sys.argv[2], sys.argv[3]))
    else:
        print("usage: knowledge_graph.py stats | relations <id> | path <a> <b>")
