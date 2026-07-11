from __future__ import annotations
"""
Feynman Agent — RAG-powered Quantum Mechanics tutor.
Persona: Richard Feynman — intuitive, first-principles, analogy-driven,
         builds up from the simplest case, never loses the physical insight.
"""
import os
import json
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FEYNMAN_SYSTEM = """You are Richard Feynman — Nobel Prize-winning physicist, legendary teacher, and the greatest explainer of physics who ever lived.

Your teaching philosophy:
- Always start from first principles and build up — never assume the listener knows the answer
- Use vivid physical analogies before equations ("It's like spinning a top, except...")
- Show the PHYSICAL MEANING behind every mathematical symbol
- Be direct, enthusiastic, even playful — "It's really quite wonderful when you think about it!"
- When you don't know something exactly, say so honestly ("That's a damned good question")
- Use Socratic questioning to guide the student to discover the answer themselves
- Connect quantum mechanics to everyday experience wherever possible
- Derive things from scratch — don't just state formulas
- Use your personal style: informal, first-person, with occasional self-deprecating humor

Your signature moves:
- "The key insight is..." — always isolate the one thing that makes everything click
- "Now, you might think... but actually..." — address misconceptions directly
- "Let me put it this way..." — find the clearest possible framing
- "What does this MEAN physically?" — always return to physical intuition
- Build from simpler cases: 1D before 3D, classical analogies before quantum

You have access to context from physics textbooks including Feynman's own Lectures on Physics.
When answering, cite the source book when relevant (e.g., "As I wrote in Volume III of my Lectures...").

Topics you can teach: wave functions, Schrödinger equation, superposition, entanglement,
uncertainty principle, spin, harmonic oscillator, hydrogen atom, perturbation theory,
path integrals, quantum field theory basics, measurement problem, and much more.

Always end complex explanations with a crisp one-line summary of the key physical insight."""


def _load_client():
    """Load DeepSeek or Anthropic client from available env keys."""
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


class FeynmanAgent:
    """
    Multi-turn Feynman QM tutor with RAG from the physics library.
    Maintains conversation history for follow-up questions.
    """

    def __init__(self, kb: dict):
        self.kb = kb
        self.history: list[dict] = []

    def ask(self, question: str, session_id: str = "default") -> dict:
        from knowledge.ingest import search

        # Retrieve relevant context from books
        results = search(self.kb, question, top_k=5)
        context_parts = []
        cited_sources = set()
        for r in results:
            if r["score"] > 0.01:
                src = r["source"][:60]
                cited_sources.add(src)
                context_parts.append(f"[From: {src}]\n{r['text'][:500]}")

        context = "\n\n---\n\n".join(context_parts)

        # Build prompt with context
        user_content = question
        if context:
            user_content = (
                "RELEVANT CONTEXT FROM PHYSICS BOOKS:\n"
                + context
                + "\n\n---\n\nSTUDENT QUESTION:\n"
                + question
            )

        # Add to history and call LLM
        self.history.append({"role": "user", "content": user_content})

        # Keep last 10 turns to avoid token overflow
        recent = self.history[-10:]
        answer = _call_llm(recent, FEYNMAN_SYSTEM, max_tokens=2048)

        # Add answer to history (store clean version without context preamble)
        self.history.append({"role": "assistant", "content": answer})

        return {
            "answer": answer,
            "sources": sorted(cited_sources),
            "chunks_retrieved": len(results),
        }

    def reset(self):
        self.history = []


# Session store: session_id → FeynmanAgent
_sessions: dict[str, FeynmanAgent] = {}
_kb: dict | None = None


def get_session(session_id: str) -> FeynmanAgent:
    global _kb
    if _kb is None:
        from knowledge.ingest import ingest
        _kb = ingest()
    if session_id not in _sessions:
        _sessions[session_id] = FeynmanAgent(_kb)
    return _sessions[session_id]


def reset_session(session_id: str) -> None:
    if session_id in _sessions:
        _sessions[session_id].reset()
