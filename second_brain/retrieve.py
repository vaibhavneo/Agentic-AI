"""
Second Brain MVP — Retrieve (Phase 2)
TF-IDF over memory/index/chunks.json. Pure Python (no sklearn dependency),
same approach as brain/memory/memory_system.py's episodic retrieval.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

INDEX_PATH = Path(__file__).parent.parent / "memory" / "index" / "chunks.json"

_STOP = set("the a an and or of to in for on with is are was were be been this that it as by from at".split())


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 2]


class Retriever:
    def __init__(self, index_path: Path = INDEX_PATH):
        data = json.loads(Path(index_path).read_text())
        self.chunks = data["chunks"]
        self.doc_tokens = [_tokens(c["text"]) for c in self.chunks]
        self.df: Counter = Counter()
        for toks in self.doc_tokens:
            self.df.update(set(toks))
        self.n = len(self.chunks)

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        q = _tokens(query)
        scores = []
        for i, toks in enumerate(self.doc_tokens):
            tf = Counter(toks)
            # smoothed idf (sklearn-style): strictly positive, so tiny corpora
            # (even a single chunk) remain retrievable; raw log(n/(1+df)) went
            # negative when df ≈ n, silently blanking 1-2 chunk corpora.
            score = sum(
                (tf[t] / max(len(toks), 1))
                * (math.log((1 + self.n) / (1 + self.df[t])) + 1)
                for t in q if t in tf
            )
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        return [
            {"score": round(s, 4), "source": self.chunks[i]["source"],
             "text": self.chunks[i]["text"]}
            for s, i in scores[:top_k]
        ]


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "agent design patterns"
    r = Retriever()
    for hit in r.retrieve(query):
        print(f"[{hit['score']}] {hit['source']}\n  {hit['text'][:150]}...\n")
