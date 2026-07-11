"""
Memory System — implements all 5 memory types from Huyen + Arsanjani:
  1. Working memory  (in-context, managed by caller)
  2. Episodic memory (past events, JSON file-backed)
  3. Semantic memory (knowledge, JSON file-backed with TF-IDF retrieval)
  4. Procedural memory (skills / tool specs, loaded at startup)
  5. Shared epistemic memory (cross-agent blackboard)
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── helpers ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())

def _tfidf_score(query_tokens: list[str], doc_tokens: list[str],
                 idf: dict[str, float]) -> float:
    freq: dict[str, int] = defaultdict(int)
    for t in doc_tokens:
        freq[t] += 1
    total = len(doc_tokens) or 1
    return sum(
        (freq[t] / total) * idf.get(t, 0.0)
        for t in query_tokens
        if t in freq
    )

def _build_idf(docs: list[list[str]]) -> dict[str, float]:
    n = len(docs) or 1
    df: dict[str, int] = defaultdict(int)
    for doc in docs:
        for t in set(doc):
            df[t] += 1
    return {t: math.log((n + 1) / (cnt + 1)) + 1.0 for t, cnt in df.items()}


# ── Episodic Memory ────────────────────────────────────────────────────────

class EpisodicMemory:
    """Stores time-stamped events (conversations, task outcomes)."""

    def __init__(self, path: Path):
        self._path = path / "episodic.json"
        self._events: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                return []
        return []

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._events, indent=2))

    def store(self, event_type: str, content: str,
              metadata: dict | None = None) -> None:
        self._events.append({
            "id": f"ep_{int(time.time()*1000)}",
            "type": event_type,
            "content": content,
            "metadata": metadata or {},
            "timestamp": _now(),
        })
        # cap at 500 events (forget oldest)
        if len(self._events) > 500:
            self._events = self._events[-500:]
        self._save()

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._events:
            return []
        q_tokens = _tokenize(query)
        all_tokens = [_tokenize(e["content"]) for e in self._events]
        idf = _build_idf(all_tokens)
        scored = [
            (e, _tfidf_score(q_tokens, doc, idf))
            for e, doc in zip(self._events, all_tokens)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, s in scored[:top_k] if s > 0]

    def recent(self, n: int = 10) -> list[dict]:
        return self._events[-n:]


# ── Semantic Memory ────────────────────────────────────────────────────────

class SemanticMemory:
    """Stores knowledge facts — world knowledge, domain facts, Q&A pairs."""

    def __init__(self, path: Path):
        self._path = path / "semantic.json"
        self._facts: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                return []
        return []

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._facts, indent=2))

    def store(self, key: str, value: str, source: str = "") -> None:
        # update existing key if present
        for fact in self._facts:
            if fact["key"] == key:
                fact["value"] = value
                fact["source"] = source
                fact["updated"] = _now()
                self._save()
                return
        self._facts.append({
            "key": key,
            "value": value,
            "source": source,
            "created": _now(),
            "updated": _now(),
        })
        self._save()

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._facts:
            return []
        q_tokens = _tokenize(query)
        docs = [_tokenize(f"{f['key']} {f['value']}") for f in self._facts]
        idf = _build_idf(docs)
        scored = [
            (f, _tfidf_score(q_tokens, doc, idf))
            for f, doc in zip(self._facts, docs)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [f for f, s in scored[:top_k] if s > 0]


# ── Blackboard (Shared Epistemic Memory) ──────────────────────────────────

class Blackboard:
    """Shared key-value store for cross-agent communication."""

    def __init__(self, path: Path):
        self._path = path / "blackboard.json"
        self._store: dict[str, Any] = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._store, indent=2, default=str))

    def write(self, key: str, value: Any, agent: str = "") -> None:
        self._store[key] = {
            "value": value,
            "agent": agent,
            "timestamp": _now(),
        }
        self._save()

    def read(self, key: str) -> Any:
        entry = self._store.get(key)
        return entry["value"] if entry else None

    def read_all(self) -> dict:
        return {k: v["value"] for k, v in self._store.items()}

    def keys(self) -> list[str]:
        return list(self._store.keys())


# ── Unified Memory Interface ───────────────────────────────────────────────

class MemorySystem:
    """
    Single interface to all memory types.
    Used by orchestrator and agents via dependency injection.
    """

    def __init__(self, memory_dir: Path):
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.episodic   = EpisodicMemory(memory_dir)
        self.semantic   = SemanticMemory(memory_dir)
        self.blackboard = Blackboard(memory_dir)

    def remember_event(self, event_type: str, content: str,
                       metadata: dict | None = None) -> None:
        self.episodic.store(event_type, content, metadata)

    def remember_fact(self, key: str, value: str, source: str = "") -> None:
        self.semantic.store(key, value, source)

    def recall(self, query: str, top_k: int = 5) -> dict:
        """Retrieve from both episodic and semantic memory."""
        return {
            "episodic": self.episodic.retrieve(query, top_k),
            "semantic": self.semantic.retrieve(query, top_k),
        }

    def format_for_context(self, query: str, max_tokens: int = 2000) -> str:
        """Format retrieved memories as a context string for LLM injection."""
        results = self.recall(query)
        lines: list[str] = []

        if results["semantic"]:
            lines.append("## Relevant Knowledge")
            for f in results["semantic"]:
                lines.append(f"- **{f['key']}**: {f['value']}")

        if results["episodic"]:
            lines.append("\n## Relevant Past Events")
            for e in results["episodic"]:
                ts = e.get("timestamp", "")[:10]
                lines.append(f"- [{ts}] {e['type']}: {e['content'][:200]}")

        context = "\n".join(lines)
        # rough token estimation: 4 chars ≈ 1 token
        if len(context) > max_tokens * 4:
            context = context[: max_tokens * 4] + "\n[...truncated]"
        return context
