"""
assistant — research first, then (when a model is available) grounded synthesis.

Vendored beside agent_core.py / live_feed.py / live_knowledge.py (source:
agent-hosting/shared/; sync with shared/sync.py). Standard library only.

An app's AI Chat answers in two stages:

  1. RESEARCH   the app's agent team runs (its own data, live feeds, the
                knowledge layer — local KB first, then FRED / quotes / news /
                SEC / Wikipedia / web search). Each section streams as it lands.
  2. SYNTHESIS  if a language model is available, it writes the answer FROM
                THAT RESEARCH ONLY, citing the same [n] sources. A verifier
                then removes any sentence carrying a number the research does
                not contain, or a forbidden claim. With no model (or if the
                verifier leaves nothing), the researched answer stands as is.

Providers, first available wins (LLM_PROVIDER forces one):
    anthropic   ANTHROPIC_API_KEY   (ANTHROPIC_MODEL, default claude-haiku-4-5-20251001)
    openai      OPENAI_API_KEY      (OPENAI_MODEL, default gpt-4.1-mini)
    gemini      GEMINI_API_KEY      (GEMINI_MODEL, default gemini-2.5-flash; free tier)
    groq        GROQ_API_KEY        (GROQ_MODEL, default llama-3.3-70b-versatile; free tier)
    openrouter  OPENROUTER_API_KEY  (OPENROUTER_MODEL)
    deepseek    DEEPSEEK_API_KEY    (DEEPSEEK_MODEL, default deepseek-flash) — skipped when its balance is 0
    ollama      a local Ollama at OLLAMA_URL (default http://127.0.0.1:11434; OLLAMA_MODEL, default llama3.2)

`local_only=True` (finance: a question about you) restricts synthesis to the
local model — your numbers never go to a cloud API.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from typing import Any, Dict, Iterator, List, Optional

_down: Dict[str, float] = {}          # provider -> time it may be retried
_health: Dict[str, tuple] = {}        # provider -> (checked_at, ok)
_lock = threading.Lock()
DOWN_S = 600

OPENAI_COMPAT = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/chat/completions", "OPENAI_MODEL", "gpt-4.1-mini"),
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "GEMINI_MODEL", "gemini-2.5-flash"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions", "GROQ_MODEL",
             "llama-3.3-70b-versatile"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_MODEL",
                   "meta-llama/llama-3.3-70b-instruct:free"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/chat/completions", "DEEPSEEK_MODEL", "deepseek-flash"),
}
ORDER = ["anthropic", "openai", "gemini", "groq", "openrouter", "deepseek", "ollama"]
CLOUD = set(ORDER) - {"ollama"}


def _post(url: str, body: Dict[str, Any], headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _get(url: str, headers: Dict[str, str], timeout: float = 5) -> Dict[str, Any]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read())


def _healthy(name: str) -> bool:
    """Cheap, cached checks for the providers that can be checked for free."""
    with _lock:
        if _down.get(name, 0) > time.time():
            return False
        h = _health.get(name)
        if h and time.time() - h[0] < 300:
            return h[1]
    ok = True
    try:
        if name == "deepseek":
            d = _get("https://api.deepseek.com/user/balance",
                     {"Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY', '')}"})
            ok = bool(d.get("is_available"))
        elif name == "ollama":
            _get(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/tags", {}, timeout=2)
    except Exception:
        ok = False
    with _lock:
        _health[name] = (time.time(), ok)
    return ok


def configured() -> List[str]:
    out = []
    forced = os.environ.get("LLM_PROVIDER", "").strip().lower()
    for name in ([forced] if forced in ORDER else ORDER):
        if name == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            out.append(name)
        elif name in OPENAI_COMPAT and os.environ.get(OPENAI_COMPAT[name][0]):
            out.append(name)
        elif name == "ollama":
            out.append(name)
    return out


def provider(local_only: bool = False) -> Optional[Dict[str, str]]:
    """The first configured, healthy provider, or None."""
    for name in configured():
        if local_only and name in CLOUD:
            continue
        if _healthy(name):
            return {"provider": name, "model": _model(name)}
    return None


def status() -> Dict[str, Any]:
    p = provider()
    return {"available": bool(p), **(p or {}), "configured": configured(),
            "local_available": bool(provider(local_only=True)),
            "reason": None if p else ("no model is reachable: every configured key is out of balance or rejected, "
                                      "and no local Ollama is running" if configured() != ["ollama"] else
                                      "no API key is set and no local Ollama is running")}


def _model(name: str) -> str:
    if name == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    if name == "ollama":
        return os.environ.get("OLLAMA_MODEL", "llama3.2")
    env, default = OPENAI_COMPAT[name][2], OPENAI_COMPAT[name][3]
    return os.environ.get(env, default)


def complete(system: str, user: str, max_tokens: int = 600, timeout: float = 45.0,
             local_only: bool = False) -> Optional[Dict[str, str]]:
    """One completion from the first working provider; a provider that fails
    is set aside for 10 minutes and the next is tried. None if none works."""
    for name in configured():
        if local_only and name in CLOUD:
            continue
        if not _healthy(name):
            continue
        model = _model(name)
        try:
            if name == "anthropic":
                d = _post("https://api.anthropic.com/v1/messages",
                          {"model": model, "max_tokens": max_tokens, "system": system,
                           "messages": [{"role": "user", "content": user}]},
                          {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}, timeout)
                text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
            else:
                if name == "ollama":
                    url, headers = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + \
                        "/v1/chat/completions", {}
                else:
                    key_env, url, _, _ = OPENAI_COMPAT[name]
                    headers = {"Authorization": f"Bearer {os.environ[key_env]}"}
                d = _post(url, {"model": model, "max_tokens": max_tokens, "temperature": 0.2,
                                "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": user}]}, headers, timeout)
                text = (d.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()     # reasoning models' scratchpad
            if text:
                return {"text": text, "provider": name, "model": model}
        except Exception:
            with _lock:
                _down[name] = time.time() + DOWN_S
    return None


# ── Verification ──────────────────────────────────────────────────────────

_NUM = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?%?")
FORBIDDEN = re.compile(r"\b(guarantee(d|s)?|risk[- ]free|can(?:'|no)t lose|sure thing|price target|"
                       r"you should (buy|sell|short)|will definitely)\b", re.I)


def _nums(text: str) -> List[str]:
    out = []
    for m in _NUM.findall(re.sub(r"\[\d+\]", " ", text or "")):
        n = m.replace("$", "").replace(",", "").replace("+", "").rstrip("%").lstrip("-")
        if n:
            out.append(n.rstrip("0").rstrip(".") if "." in n else n)
    return out


def _unsupported(sentence: str, allowed: set) -> List[str]:
    """Numbers in the sentence that the evidence does not contain. A bare
    whole number up to 10 ("3 points") is a count, not a figure — but "7%"
    or "$7" is a figure and must be in the evidence."""
    bad = []
    for raw in _NUM.findall(re.sub(r"\[\d+\]", " ", sentence)):
        n = _nums(raw)
        if not n:
            continue
        if re.fullmatch(r"\d{1,2}", raw.strip()) and int(raw) <= 10:
            continue
        if n[0] not in allowed:
            bad.append(n[0])
    return bad


def verify(answer: str, evidence: str, question: str = "") -> Dict[str, Any]:
    """Keep only sentences whose every number appears in the evidence (or the
    question, or is a small count), and that make no forbidden claim."""
    allowed = set(_nums(evidence)) | set(_nums(question))
    kept, removed = [], []
    for para in answer.split("\n"):
        sents = re.split(r"(?<=[.!?])\s+", para)
        good = []
        for s in sents:
            bad = _unsupported(s, allowed)
            if bad or FORBIDDEN.search(s):
                removed.append({"sentence": s, "unsupported": bad, "forbidden": bool(FORBIDDEN.search(s))})
            else:
                good.append(s)
        kept.append(" ".join(good))
    text = "\n".join(kept).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return {"text": text, "removed": removed}


SYSTEM = """You are the AI assistant inside {app}. Answer the user's question using ONLY the RESEARCH below
(the app's own data, live market data and cited sources gathered for this question).
Rules:
- Every number you write must appear in the RESEARCH. Never estimate, extrapolate or invent figures.
- Cite sources with the same [n] markers the RESEARCH uses, right after the claim they support.
- Lead with the direct answer in one or two sentences, then the key supporting points (short bullets are fine).
- If the RESEARCH does not answer part of the question, say so plainly instead of filling the gap.
- No trading instructions ("you should buy/sell"), no guarantees, no price targets.
- At most {words} words. Plain language."""


def synthesize(question: str, research: str, app: str, local_only: bool = False,
               history: Optional[List[Dict[str, str]]] = None, words: int = 220) -> Optional[Dict[str, Any]]:
    """A grounded, verified answer from the research — or None (no model, or
    the verifier left nothing worth showing)."""
    convo = ""
    if history:
        convo = "\n".join(f"{h.get('role', 'user')}: {h.get('content', '')[:400]}" for h in history[-4:]) + "\n\n"
    out = complete(SYSTEM.format(app=app, words=words),
                   f"{convo}QUESTION: {question}\n\nRESEARCH:\n{research[:12000]}", local_only=local_only)
    if not out:
        return None
    v = verify(out["text"], research, question)
    if len(v["text"]) < 20:
        return None
    return {"text": v["text"], "provider": out["provider"], "model": out["model"], "removed": v["removed"]}


def _sources_block(answer: str) -> str:
    """The research answer's citation list (a 'Sources:' block or line), so the
    synthesized text's [n] markers still resolve."""
    ms = list(re.finditer(r"(?m)^Sources:", answer))
    return "\n\n" + answer[ms[-1].start():].strip() if ms else ""


def stream(events: Iterator[Dict[str, Any]], question: str, app: str, local_only: bool = False,
           history: Optional[List[Dict[str, str]]] = None) -> Iterator[Dict[str, Any]]:
    """Wrap an agent team's run_stream(): pass research events through, then
    — if a model is available and the research answered — a synthesis step.

    Extra events:  {"type": "synthesizing", "provider", "model"}
    The final result gains: answer (synthesized when it happened),
    research_answer (the team's own), synthesis {provider, model, removed} or
    synthesis_skipped (why)."""
    final = None
    for ev in events:
        if ev["type"] == "final":
            final = ev["result"]
        else:
            yield ev
    if final is None:
        return
    final = dict(final, research_answer=final.get("answer"))
    if final.get("outcome") != "ANSWERED":
        final["synthesis_skipped"] = "the research did not produce an answer (or a guardrail stopped it)"
        yield {"type": "final", "result": final}
        return
    p = provider(local_only=local_only)
    if not p:
        final["synthesis_skipped"] = ("no local model is running (questions about you are only sent to a "
                                      "local model)" if local_only else status()["reason"])
        yield {"type": "final", "result": final}
        return
    yield {"type": "synthesizing", **p}
    syn = synthesize(question, final["answer"], app, local_only=local_only, history=history)
    if syn:
        final["answer"] = syn["text"] + _sources_block(final["answer"])
        final["synthesis"] = {k: syn[k] for k in ("provider", "model", "removed")}
    else:
        final["synthesis_skipped"] = "the model did not return an answer the verifier could keep"
    yield {"type": "final", "result": final}
