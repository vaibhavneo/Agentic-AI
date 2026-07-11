from __future__ import annotations
"""
AI Learning Agent — expert tutor for Agentic AI, LLMs, and Generative AI.
RAG-powered from 170+ books and 31 research papers.
"""
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TUTOR_SYSTEM = """You are an expert AI research tutor with encyclopedic knowledge of:
- Agentic AI systems (multi-agent, ReAct, RAG, tool use, memory, orchestration)
- Large Language Models (architecture, training, fine-tuning, alignment, evaluation)
- Generative AI (diffusion models, image/audio/video generation, multimodal systems)
- AI Frameworks (LangChain, LangGraph, CrewAI, AutoGen, OpenAI SDK, Google ADK)
- Production AI engineering (deployment, reliability, observability, evaluation)
- AI research papers (you can explain and critique arxiv papers)

Your teaching style:
- Start with the core intuition before diving into details
- Use concrete examples and analogies
- Connect concepts across books and papers you've read
- When referencing context from books, cite the source naturally ("According to Chip Huyen's AI Engineering...")
- Give structured answers for complex topics: concept → why it matters → how it works → example
- For research papers: summarize the key contribution, method, results, and limitations
- Proactively suggest related topics and learning paths
- Be honest about uncertainty ("This is debated in the field..." or "The research is evolving...")

Depth levels you can operate at:
- Beginner: analogies, high-level intuition, no math
- Intermediate: architecture, patterns, implementation concepts
- Expert: mathematical details, research nuances, trade-offs, open problems

Adapt to the student's level based on how they ask questions."""


def _load_client():
    for env_path in [
        Path(__file__).parent / ".env",
        Path(__file__).parent.parent / "health-agent" / ".env",
        Path(__file__).parent.parent / "stock_agent" / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if v.strip() not in ("", "paste_your_key_here"):
                        os.environ.setdefault(k.strip(), v.strip())

    dk = os.getenv("DEEPSEEK_API_KEY", "")
    ak = os.getenv("ANTHROPIC_API_KEY", "")
    if dk:
        from openai import OpenAI
        return OpenAI(api_key=dk, base_url="https://api.deepseek.com"), "deepseek"
    if ak:
        import anthropic
        return anthropic.Anthropic(api_key=ak), "anthropic"
    raise RuntimeError("No API key found. Add DEEPSEEK_API_KEY to health-agent/.env")


_client = None
_provider = None


def _get_client():
    global _client, _provider
    if _client is None:
        _client, _provider = _load_client()
    return _client, _provider


def _call_llm(messages: list[dict], system: str, max_tokens: int = 2048) -> str:
    client, provider = _get_client()
    if provider == "deepseek":
        resp = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}] + messages,
        )
        return resp.choices[0].message.content or ""
    else:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return resp.content[0].text


class LearningAgent:
    """Multi-turn AI learning tutor with RAG from the full knowledge base."""

    def __init__(self, kb: dict):
        self.kb = kb
        self.history: list[dict] = []

    def ask(self, question: str, category: Optional[str] = None) -> dict:
        from knowledge.ingest import search

        results = search(self.kb, question, top_k=6, category=category if category != "All" else None)

        context_parts = []
        cited: list[dict] = []
        for r in results:
            if r["score"] > 0.005:
                short_src = r["source"].split("(")[0].strip()[:55]
                context_parts.append(f"[Source: {short_src} | Category: {r['category']}]\n{r['text'][:600]}")
                cited.append({"source": r["source"], "category": r["category"], "score": r["score"]})

        context = "\n\n---\n\n".join(context_parts)
        user_content = question
        if context:
            user_content = (
                "RELEVANT CONTEXT FROM YOUR KNOWLEDGE BASE:\n\n"
                + context
                + "\n\n---\n\nSTUDENT QUESTION:\n"
                + question
            )

        self.history.append({"role": "user", "content": user_content})
        recent = self.history[-12:]
        answer = _call_llm(recent, TUTOR_SYSTEM, max_tokens=2048)
        self.history.append({"role": "assistant", "content": answer})

        # Deduplicate citations
        seen = set()
        unique_cited = []
        for c in cited:
            key = c["source"][:40]
            if key not in seen:
                seen.add(key)
                unique_cited.append(c)

        return {"answer": answer, "sources": unique_cited[:5]}

    def suggest_path(self, topic: str) -> str:
        """Generate a learning path for a topic."""
        prompt = (
            f"Create a structured 5-step learning path for someone who wants to master: {topic}\n"
            "Format as numbered steps, each with: what to learn, why it matters, and suggested resources from the knowledge base."
        )
        resp = _call_llm([{"role": "user", "content": prompt}], TUTOR_SYSTEM, max_tokens=1024)
        return resp

    def reset(self):
        self.history = []


# Session management
_sessions: dict[str, LearningAgent] = {}
_kb: Optional[dict] = None


def get_session(session_id: str) -> LearningAgent:
    global _kb
    if _kb is None:
        from knowledge.ingest import load_index, ingest
        _kb = load_index()
        if _kb is None:
            print("No knowledge base found — running ingestion...")
            _kb = ingest(verbose=True)
    if session_id not in _sessions:
        _sessions[session_id] = LearningAgent(_kb)
    return _sessions[session_id]


def reset_session(session_id: str) -> None:
    if session_id in _sessions:
        _sessions[session_id].reset()


def get_kb_stats() -> dict:
    global _kb
    if _kb is None:
        from knowledge.ingest import load_index
        _kb = load_index()
    if not _kb:
        return {}
    return {
        "total_chunks": _kb.get("total", 0),
        "total_books": _kb.get("total_books", 0),
        "categories": _kb.get("categories", {}),
    }
