"""
agent_core — a small, deterministic multi-agent runtime.

Vendored into each app beside live_knowledge.py (keep copies identical; source:
agent-hosting/shared/, sync with shared/sync.py). Standard library only.

One question flows through one central ORCHESTRATOR:

    guardrails ─► route ─► plan ─► execute (parallel stages) ─► compose ─► critique ─► remember
       │            │        │            │                        │           │            │
    refuse or    agents   dependency   each agent posts a      lead with    critics drop   session +
    clarify      BID on   layers       Finding to the shared   the best     or fix what    episodic
    before any   the task (handoffs)   BLACKBOARD; later       findings,    they can't     memory,
    work runs                          stages read earlier     in priority  verify         full trace
                                       ones

The patterns, and where each lives (Gullí, *Agentic Design Patterns*; the MAS
supervisor topology):

    Routing                 Agent.bid() — every specialist scores its own relevance
    Plan-and-Execute        Orchestrator.plan(): chosen agents + their depends_on, layered
    Parallelization         each layer runs concurrently, each agent under its own timeout
    Multi-agent collab.     Blackboard: findings and shared facts every later agent can read
    Orchestrator–subagent   the Orchestrator owns the loop; agents never call each other
    Handoff                 depends_on: a synthesizer runs after the specialists it needs
    Tool use                agents wrap the app's existing tools (ledger, chart, quotes…)
    RAG                     a knowledge agent over live_knowledge.Pipeline
    Reflection / critique   Critic.review(): checks the draft; may drop sentences or veto
    Guardrails              input guardrails (refuse / clarify) and output critics
    Exception handling      a failing or slow agent is recorded (ERROR / TIMEOUT), never fatal;
                            a fallback agent answers when nothing else does
    Memory                  Session (subject carry-over, recent turns) + Episodic (SQLite log)
    Resource-aware          max_agents and a wall-clock budget; low bids are not run
    Human-in-the-loop       a guardrail or an empty plan returns a CLARIFY outcome, not a guess
    Observability           every step is in the returned trace with timings
    Structured output       the result is a dict with a stable shape

Nothing here generates text. Agents compute or quote; the orchestrator orders
and checks. An LLM, where an app has one, may reword the final answer — never
add to it.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

VERSION = "1.0.0"

OK, DECLINED, ERROR, TIMEOUT, SKIPPED = "OK", "DECLINED", "ERROR", "TIMEOUT", "SKIPPED"
ANSWERED, CLARIFY, REFUSED, EMPTY = "ANSWERED", "CLARIFY", "REFUSED", "EMPTY"


# ── Contracts ─────────────────────────────────────────────────────────────

@dataclass
class Task:
    question: str
    ctx: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)   # recent turns from session memory

    @property
    def text(self) -> str:
        return self.question.lower()


@dataclass
class Finding:
    """What one agent contributes. `lines` are answer-ready sentences (markdown
    allowed); `facts` are the structured values behind them; `sources` are
    citations [{title, source, url, fetched_at}]."""
    agent: str
    status: str = OK
    lines: List[str] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    reason: str = ""
    headline: str = ""
    ms: int = 0
    priority: int = 50

    @property
    def ok(self) -> bool:
        return self.status == OK and bool(self.lines or self.facts)

    def to_dict(self) -> Dict[str, Any]:
        return {"agent": self.agent, "status": self.status, "lines": self.lines, "facts": _jsonable(self.facts),
                "sources": self.sources, "confidence": self.confidence, "reason": self.reason,
                "headline": self.headline, "ms": self.ms}


class Agent:
    """A specialist. Subclass and set name/role; implement bid() and run().

    bid(task) -> 0..1: how much this agent has to say about the task. The
    orchestrator runs agents whose bid clears its threshold (plus their
    dependencies). run(task, board) -> Finding; read upstream findings from
    `board`. Raise or return status=DECLINED when there is nothing to say —
    never invent."""
    name = "agent"
    role = ""
    priority = 50            # lower = earlier in the composed answer
    timeout_s = 15.0
    depends_on: Tuple[str, ...] = ()
    always = False           # run on every task (e.g. a synthesizer that decides itself)
    yields_to: Tuple[str, ...] = ()   # a gap-filler: stands down when any of these bids above threshold

    def bid(self, task: Task) -> float:
        return 0.0

    def run(self, task: Task, board: "Blackboard") -> Finding:
        raise NotImplementedError

    def finding(self, **kw) -> Finding:
        kw.setdefault("priority", self.priority)
        return Finding(agent=self.name, **kw)

    def decline(self, reason: str) -> Finding:
        return Finding(agent=self.name, status=DECLINED, reason=reason, priority=self.priority)


class FnAgent(Agent):
    """An agent from two functions — for wrapping an app's existing tools."""

    def __init__(self, name: str, bid: Callable[[Task], float], run: Callable[[Task, "Blackboard"], Finding],
                 role: str = "", priority: int = 50, timeout_s: float = 15.0, depends_on: Sequence[str] = (),
                 always: bool = False):
        self.name, self.role, self.priority, self.timeout_s = name, role, priority, timeout_s
        self.depends_on, self.always = tuple(depends_on), always
        self._bid, self._run = bid, run

    def bid(self, task):
        return self._bid(task)

    def run(self, task, board):
        f = self._run(task, board)
        f.agent, f.priority = self.name, (f.priority if f.priority != 50 else self.priority)
        return f


class Blackboard:
    """Shared workspace: every finding, plus facts any agent publishes."""

    def __init__(self):
        self._lock = threading.Lock()
        self.findings: Dict[str, Finding] = {}
        self.facts: Dict[str, Any] = {}

    def post(self, f: Finding) -> None:
        with self._lock:
            self.findings[f.agent] = f
            if f.status == OK:
                for k, v in f.facts.items():
                    self.facts.setdefault(k, v)

    def get(self, agent: str) -> Optional[Finding]:
        f = self.findings.get(agent)
        return f if f and f.status == OK else None

    def ok(self) -> List[Finding]:
        return [f for f in self.findings.values() if f.ok]

    def all_text(self) -> str:
        parts = []
        for f in self.ok():
            parts += f.lines
            parts.append(json.dumps(_jsonable(f.facts), default=str))
        return "\n".join(parts)


@dataclass
class Draft:
    headline: str
    sections: List[Tuple[str, List[str]]]          # (agent, lines) in answer order
    sources: List[Dict[str, Any]]
    notes: List[str] = field(default_factory=list)

    def text(self) -> str:
        body = "\n\n".join("\n".join(lines) for _, lines in self.sections if lines)
        if self.notes:
            body += "\n\n" + "\n".join(self.notes)
        return body.strip()


class Guardrail:
    """Input guardrail. Return None to continue, or (outcome, message) to stop
    before any agent runs: (REFUSED, why) or (CLARIFY, what to ask)."""
    name = "guardrail"

    def check(self, task: Task) -> Optional[Tuple[str, str]]:
        return None


class Critic:
    """Output critic (reflection). Inspect the draft against the blackboard.
    Return a list of issues; each may carry `drop` (a line to remove) or `veto`
    (True: the whole answer is unsafe, use the fallback text)."""
    name = "critic"

    def review(self, task: Task, draft: Draft, board: Blackboard) -> List[Dict[str, Any]]:
        return []


# ── Built-in critics ─────────────────────────────────────────────────────

_NUM = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?%?")


def numbers_in(text: str) -> List[str]:
    out = []
    for m in _NUM.findall(text or ""):
        n = m.replace("$", "").replace(",", "").replace("+", "").rstrip("%")
        if n and n not in ("-",):
            out.append(n)
    return out


class NumbersTracedCritic(Critic):
    """Every number in a line written by a SYNTHESIZER (an agent that combines
    other findings) must appear in an upstream finding's lines or facts, or be
    derivable as a difference/ratio the synthesizer declares in its facts
    under 'derived'. A number nobody computed is removed with its line."""
    name = "numbers_traced"

    def __init__(self, synthesizers: Sequence[str]):
        self.synthesizers = set(synthesizers)

    def review(self, task, draft, board):
        issues = []
        for agent, lines in draft.sections:
            if agent not in self.synthesizers:
                continue
            f = board.findings.get(agent)
            derived = {str(x) for x in ((f.facts.get("derived") or {}).values() if f else [])}
            upstream = "\n".join(
                "\n".join(o.lines) + json.dumps(_jsonable(o.facts), default=str)
                for name, o in board.findings.items() if name != agent and o.status == OK)
            known = set(numbers_in(upstream)) | {n.replace(",", "") for n in derived} | set(numbers_in(" ".join(derived)))
            for line in lines:
                missing = [n for n in numbers_in(line) if n not in known and _strip0(n) not in {_strip0(k) for k in known}]
                if missing:
                    issues.append({"critic": self.name, "agent": agent, "drop": line,
                                   "why": f"number(s) {', '.join(missing)} not found in any specialist's finding"})
        return issues


class ForbiddenClaimsCritic(Critic):
    """Phrases no answer from these apps may contain: certainty about markets
    or fate, and instructions to trade."""
    name = "forbidden_claims"
    DEFAULT = (r"\bguarantee(d|s)?\b", r"\brisk[- ]free\b", r"\bcan(?:'|no)t lose\b", r"\bsure thing\b",
               r"\bprice target\b", r"\byou should (buy|sell|short)\b", r"\bwill definitely\b")

    # Reporting what a cited source says ("analysts' price targets [2]") is
    # not the app making the claim; these patterns are allowed on cited lines.
    QUOTED_OK = (r"\bprice target\b",)

    def __init__(self, patterns: Sequence[str] = DEFAULT):
        self.rx = [re.compile(p, re.I) for p in patterns]

    def review(self, task, draft, board):
        issues = []
        for agent, lines in draft.sections:
            for line in lines:
                cited = bool(re.search(r"\[\d+\]", line))
                hit = next((r.pattern for r in self.rx if r.search(line)
                            and not (cited and r.pattern in self.QUOTED_OK)), None)
                if hit and not _quoted_source_line(line):
                    issues.append({"critic": self.name, "agent": agent, "drop": line, "why": f"matches {hit}"})
        return issues


class CitationCritic(Critic):
    """A finding that declares sources must cite them: a line from such an
    agent carrying a figure needs an [n] marker, or it is dropped."""
    name = "citations"

    def __init__(self, cited_agents: Sequence[str]):
        self.cited = set(cited_agents)

    def review(self, task, draft, board):
        issues = []
        for agent, lines in draft.sections:
            if agent not in self.cited:
                continue
            for line in lines:
                if line.startswith("Sources:") or line.startswith("["):
                    continue
                if numbers_in(line) and not re.search(r"\[\d+\]", line):
                    issues.append({"critic": self.name, "agent": agent, "drop": line, "why": "uncited figure"})
        return issues


def _quoted_source_line(line: str) -> bool:
    return line.startswith("Sources:") or bool(re.match(r"^\[\d+\]", line))


def _strip0(n: str) -> str:
    return n.rstrip("0").rstrip(".") if "." in n else n


# ── Memory ────────────────────────────────────────────────────────────────

class SessionMemory:
    """Short-term memory: per-session recent turns and carried slots (the
    subject of the conversation, a ticker, a chart). In process, capped, TTL'd."""

    def __init__(self, max_sessions: int = 500, max_turns: int = 12, ttl_s: float = 6 * 3600):
        self._s: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.max_sessions, self.max_turns, self.ttl_s = max_sessions, max_turns, ttl_s

    def get(self, sid: Optional[str]) -> Tuple[str, Dict[str, Any]]:
        with self._lock:
            now = time.time()
            for k in [k for k, v in self._s.items() if now - v["at"] > self.ttl_s]:
                del self._s[k]
            if not sid or sid not in self._s:
                sid = sid or uuid.uuid4().hex[:16]
                if len(self._s) >= self.max_sessions:
                    del self._s[min(self._s, key=lambda k: self._s[k]["at"])]
                self._s[sid] = {"turns": [], "slots": {}, "at": now}
            self._s[sid]["at"] = now
            return sid, self._s[sid]

    def remember(self, sid: str, question: str, answer: str, slots: Dict[str, Any]) -> None:
        with self._lock:
            s = self._s.get(sid)
            if s is None:
                return
            s["turns"] = (s["turns"] + [{"q": question, "a": answer[:600], "at": time.time()}])[-self.max_turns:]
            s["slots"].update({k: v for k, v in slots.items() if v is not None})


class EpisodicMemory:
    """Long-term memory: every orchestrated turn in SQLite — what was asked,
    which agents ran, the outcome and timings. Read back for 'what did you
    tell me about X' and for evaluating the team (agent hit rates, latency)."""

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._c() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, at REAL, session TEXT,
                         question TEXT, outcome TEXT, answer TEXT, agents TEXT, ms INTEGER)""")

    def _c(self):
        return sqlite3.connect(self.path, timeout=10)

    def record(self, session: str, question: str, outcome: str, answer: str, trace: List[Dict[str, Any]], ms: int):
        try:
            with self._c() as c:
                c.execute("INSERT INTO episodes (at, session, question, outcome, answer, agents, ms) VALUES (?,?,?,?,?,?,?)",
                          (time.time(), session, question[:500], outcome, answer[:2000],
                           json.dumps([{k: t.get(k) for k in ("agent", "status", "ms", "bid")} for t in trace]), ms))
        except sqlite3.Error:
            pass

    def recent(self, session: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        q = "SELECT at, session, question, outcome, answer, agents, ms FROM episodes"
        args: List[Any] = []
        if session:
            q += " WHERE session = ?"
            args.append(session)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._c() as c:
            rows = c.execute(q, args).fetchall()
        return [{"at": r[0], "session": r[1], "question": r[2], "outcome": r[3], "answer": r[4],
                 "agents": json.loads(r[5] or "[]"), "ms": r[6]} for r in rows]

    def search(self, words: Sequence[str], limit: int = 3, session: Optional[str] = None,
               exclude_question: Optional[str] = None) -> List[Dict[str, Any]]:
        """Earlier answered turns whose question or answer contains every word."""
        words = [w.lower() for w in words if w]
        if not words:
            return []
        q = "SELECT at, session, question, outcome, answer FROM episodes WHERE outcome = 'ANSWERED'"
        args: List[Any] = []
        for w in words:
            q += " AND (lower(question) LIKE ? OR lower(answer) LIKE ?)"
            args += [f"%{w}%", f"%{w}%"]
        if session:
            q += " AND session = ?"
            args.append(session)
        if exclude_question:
            q += " AND question != ?"
            args.append(exclude_question)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._c() as c:
            rows = c.execute(q, args).fetchall()
        return [{"at": r[0], "session": r[1], "question": r[2], "outcome": r[3], "answer": r[4]} for r in rows]

    def stats(self) -> Dict[str, Any]:
        """Per-agent run counts, OK rate and median latency — the team's report card."""
        per: Dict[str, Dict[str, Any]] = {}
        with self._c() as c:
            rows = c.execute("SELECT agents FROM episodes ORDER BY id DESC LIMIT 2000").fetchall()
        for (a,) in rows:
            for t in json.loads(a or "[]"):
                d = per.setdefault(t["agent"], {"runs": 0, "ok": 0, "ms": []})
                d["runs"] += 1
                d["ok"] += t.get("status") == OK
                if t.get("ms") is not None:
                    d["ms"].append(t["ms"])
        return {k: {"runs": v["runs"], "ok_rate": round(v["ok"] / v["runs"], 3) if v["runs"] else None,
                    "median_ms": sorted(v["ms"])[len(v["ms"]) // 2] if v["ms"] else None} for k, v in per.items()}


class RecallAgent(Agent):
    """Memory as a specialist: 'what did you tell me about NVDA earlier?' is
    answered from the episodic log — the question asked then, when, and the
    start of what was answered. Nothing is re-derived or re-worded."""
    name, role, priority, timeout_s = "recall", "what was asked and answered before (episodic memory)", 1, 5.0
    RX = re.compile(r"\b(what did (you|i) (say|tell|ask|answer)|you (told|said)|earlier|last time|before|"
                    r"remind me what|did i ask|previously)\b", re.I)
    FILLER = {"what", "did", "you", "say", "tell", "told", "said", "me", "about", "earlier", "last", "time", "before",
              "remind", "ask", "asked", "answer", "answered", "i", "previously", "the", "a", "on", "of", "my", "is"}

    def __init__(self, episodic_path: Callable[[], Optional[str]]):
        self._path = episodic_path

    def bid(self, task):
        return 0.95 if self.RX.search(task.question) else 0.0

    def run(self, task, board):
        path = self._path()
        if not path:
            return self.decline("no episodic memory configured")
        words = [w for w in re.findall(r"[a-z0-9$.%-]+", task.text) if w not in self.FILLER and len(w) > 1][:4]
        if not words:
            return self.decline("nothing named to look for")
        hits = EpisodicMemory(path).search(words, exclude_question=task.question)
        if not hits:
            return self.finding(lines=[f"I have no earlier answer about {' '.join(words)} in my memory."])
        lines = [f"**From memory** ({len(hits)} earlier answer{'s' if len(hits) > 1 else ''} about {' '.join(words)}):"]
        for h in hits:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["at"]))
            first = h["answer"].strip().split("\n")[0][:300]
            lines.append(f"- {when} — you asked \"{h['question'][:120]}\"; the answer began: {first}")
        return self.finding(lines=lines)


# ── Orchestrator ──────────────────────────────────────────────────────────

class Orchestrator:
    def __init__(self, agents: Sequence[Agent], *, critics: Sequence[Critic] = (),
                 guardrails: Sequence[Guardrail] = (), fallback: Optional[Agent] = None,
                 threshold: float = 0.5, max_agents: int = 6, budget_s: float = 40.0,
                 session_memory: Optional[SessionMemory] = None, episodic: Optional[EpisodicMemory] = None,
                 slots: Optional[Callable[[Task], Dict[str, Any]]] = None,
                 empty_text: str = "None of the specialists had anything to say about that."):
        names = [a.name for a in agents]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate agent names: {names}")
        self.agents = {a.name: a for a in agents}
        for a in agents:
            for d in a.depends_on:
                if d not in self.agents:
                    raise ValueError(f"{a.name} depends on unknown agent {d!r}")
        self.critics, self.guardrails, self.fallback = list(critics), list(guardrails), fallback
        self.threshold, self.max_agents, self.budget_s = threshold, max_agents, budget_s
        self.sessions = session_memory or SessionMemory()
        self.episodic = episodic
        self.slots = slots
        self.empty_text = empty_text

    # Routing ------------------------------------------------------------
    def bids(self, task: Task) -> Dict[str, float]:
        out = {}
        for name, a in self.agents.items():
            try:
                out[name] = max(0.0, min(1.0, float(a.bid(task))))
            except Exception:
                out[name] = 0.0
        return out

    # Planning -----------------------------------------------------------
    def plan(self, task: Task) -> Dict[str, Any]:
        bids = self.bids(task)
        # Prioritization: a generalist yields to the specialists it names, so a
        # question one of them owns is not answered twice.
        yielded = []
        for n, a in self.agents.items():
            if bids.get(n, 0) >= self.threshold and any(bids.get(y, 0) >= self.threshold for y in a.yields_to):
                bids[n] = 0.0
                yielded.append(n)
        chosen = [n for n, b in sorted(bids.items(), key=lambda kv: -kv[1]) if b >= self.threshold]
        chosen = chosen[: self.max_agents]
        for n, a in self.agents.items():
            if a.always and n not in chosen:
                chosen.append(n)
        # Pull in dependencies (a synthesizer needs its specialists).
        i = 0
        while i < len(chosen):
            for d in self.agents[chosen[i]].depends_on:
                if d not in chosen:
                    chosen.append(d)
            i += 1
        # An `always` agent with no specialist beside it has nothing to combine.
        specialists = [n for n in chosen if not self.agents[n].always]
        if not specialists:
            chosen = []
        layers: List[List[str]] = []
        done: set = set()
        remaining = list(chosen)
        while remaining:
            layer = [n for n in remaining if all(d in done or d not in chosen for d in self.agents[n].depends_on)]
            if not layer:                       # a cycle: run the rest together rather than hang
                layer = list(remaining)
            layers.append(layer)
            done.update(layer)
            remaining = [n for n in remaining if n not in done]
        return {"bids": {k: round(v, 3) for k, v in bids.items()}, "chosen": chosen, "layers": layers,
                "yielded": yielded}

    # Execution ----------------------------------------------------------
    def _run_agent(self, name: str, task: Task, board: Blackboard, deadline: float) -> Finding:
        a = self.agents[name]
        t0 = time.time()
        left = deadline - t0
        if left <= 0:
            return Finding(agent=name, status=SKIPPED, reason="the time budget was spent", priority=a.priority)
        ex = cf.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(a.run, task, board)
        try:
            f = fut.result(timeout=min(a.timeout_s, left))
            if not isinstance(f, Finding):
                f = Finding(agent=name, status=ERROR, reason=f"returned {type(f).__name__}, not a Finding")
        except cf.TimeoutError:
            f = Finding(agent=name, status=TIMEOUT, reason=f"no answer within {min(a.timeout_s, left):.0f}s")
        except Exception as e:
            f = Finding(agent=name, status=ERROR, reason=f"{type(e).__name__}: {str(e)[:200]}")
        finally:
            ex.shutdown(wait=False)
        f.agent = name
        f.ms = int((time.time() - t0) * 1000)
        if f.priority == 50 and a.priority != 50:
            f.priority = a.priority
        return f

    def execute(self, task: Task, plan: Dict[str, Any], board: Blackboard) -> None:
        for _ in self._execute_iter(task, plan, board):
            pass

    def _execute_iter(self, task: Task, plan: Dict[str, Any], board: Blackboard) -> Iterator[Finding]:
        """Run the plan layer by layer; yield each finding the moment it lands."""
        deadline = time.time() + self.budget_s
        for layer in plan["layers"]:
            with cf.ThreadPoolExecutor(max_workers=max(1, len(layer))) as ex:
                futs = {ex.submit(self._run_agent, n, task, board, deadline): n for n in layer}
                for fut in cf.as_completed(futs):
                    f = fut.result()
                    board.post(f)
                    yield f

    def _checked_section(self, task: Task, f: Finding, board: Blackboard) -> Tuple[List[str], List[Dict[str, Any]]]:
        """One finding's lines after the critics — what may be streamed now.
        The same critics run again on the whole draft at the end."""
        d = Draft(headline=f.headline, sections=[(f.agent, list(f.lines))], sources=list(f.sources))
        d, issues, vetoed = self.critique(task, d, board)
        return ([] if vetoed else (d.sections[0][1] if d.sections else [])), issues

    # Composition --------------------------------------------------------
    def compose(self, task: Task, board: Blackboard, bids: Dict[str, float]) -> Draft:
        ok = sorted(board.ok(), key=lambda f: (f.priority, -bids.get(f.agent, 0)))
        sections, sources, seen_src = [], [], {}
        said: set = set()          # sentences already in the answer, citations ignored
        for f in ok:
            lines = _unsaid(list(f.lines), said)
            if not lines:
                continue
            if f.sources:
                # Renumber this agent's [n] citations into one answer-wide list.
                remap = {}
                for s in f.sources:
                    key = (s.get("title"), s.get("url"))
                    if key not in seen_src:
                        seen_src[key] = len(sources) + 1
                        sources.append({**s, "n": seen_src[key]})
                    remap[str(s.get("n", ""))] = seen_src[key]
                lines = [re.sub(r"\[(\d+)\]", lambda m: f"[{remap.get(m.group(1), m.group(1))}]", ln) for ln in lines]
            sections.append((f.agent, lines))
        headline = next((f.headline for f in ok if f.headline), "")
        return Draft(headline=headline, sections=sections, sources=sources)

    # Reflection ---------------------------------------------------------
    def critique(self, task: Task, draft: Draft, board: Blackboard) -> Tuple[Draft, List[Dict[str, Any]], bool]:
        issues: List[Dict[str, Any]] = []
        vetoed = False
        for c in self.critics:
            try:
                found = c.review(task, draft, board) or []
            except Exception as e:
                found = [{"critic": getattr(c, "name", "critic"), "why": f"critic failed: {type(e).__name__}"}]
            for it in found:
                it.setdefault("critic", getattr(c, "name", "critic"))
                issues.append(it)
                if it.get("veto"):
                    vetoed = True
                if it.get("drop"):
                    draft.sections = [(a, [ln for ln in ls if ln != it["drop"]]) for a, ls in draft.sections]
        draft.sections = [(a, ls) for a, ls in draft.sections if ls]
        _prune_sources(draft)
        return draft, issues, vetoed

    # The loop -----------------------------------------------------------
    def run(self, question: str, ctx: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for ev in self.run_stream(question, ctx, session_id, stream_sections=False):
            if ev["type"] == "final":
                result = ev["result"]
        return result

    def run_stream(self, question: str, ctx: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None,
                   stream_sections: bool = True) -> Iterator[Dict[str, Any]]:
        """The same loop as run(), as events — for answers that arrive as they are ready:

            {"type": "plan", "session_id", "chosen", "layers", "bids"}
            {"type": "section", "agent", "role", "lines", "status", "ms"}   one per finding, as it lands,
                                                                             already through the critics
            {"type": "final", "result": <what run() returns>}               the composed, renumbered answer
        A guardrail stop yields only the final event."""
        t0 = time.time()
        sid, sess = self.sessions.get(session_id)
        task = Task(question=(question or "").strip(), ctx={**sess["slots"], **(ctx or {})}, session_id=sid,
                    history=list(sess["turns"]))
        if self.slots:
            try:
                task.ctx.update({k: v for k, v in (self.slots(task) or {}).items() if v not in (None, [], "")})
            except Exception:
                pass

        for g in self.guardrails:
            stop = g.check(task)
            if stop:
                outcome, msg = stop
                yield {"type": "final", "result": self._finish(
                    task, sid, outcome, msg, None, [], [], {"bids": {}, "chosen": [], "layers": []}, t0,
                    guardrail=getattr(g, "name", "guardrail"))}
                return

        plan = self.plan(task)
        board = Blackboard()
        if stream_sections:
            yield {"type": "plan", "session_id": sid, "chosen": plan["chosen"], "layers": plan["layers"],
                   "bids": {k: v for k, v in plan["bids"].items() if v > 0}}
        if plan["chosen"]:
            for f in self._execute_iter(task, plan, board):
                if stream_sections:
                    lines, _ = self._checked_section(task, f, board) if f.ok else ([], [])
                    yield {"type": "section", "agent": f.agent, "role": getattr(self.agents.get(f.agent), "role", ""),
                           "status": f.status, "lines": lines, "reason": f.reason, "ms": f.ms}
        if not board.ok() and self.fallback is not None:
            fb = self._run_agent(self.fallback.name, task, board, time.time() + self.budget_s) \
                if self.fallback.name in self.agents else self._run_fallback(task, board)
            board.post(fb)
            plan["fallback"] = self.fallback.name
            if stream_sections:
                lines, _ = self._checked_section(task, fb, board) if fb.ok else ([], [])
                yield {"type": "section", "agent": fb.agent, "role": getattr(self.fallback, "role", ""),
                       "status": fb.status, "lines": lines, "reason": fb.reason, "ms": fb.ms}

        draft = self.compose(task, board, plan["bids"])
        draft, issues, vetoed = self.critique(task, draft, board)
        if vetoed or not draft.sections:
            outcome = EMPTY
            text = self.empty_text if not vetoed else "I couldn't give an answer I could stand behind for that."
        else:
            outcome = ANSWERED
            text = draft.text()
            if draft.sources:
                text += "\n\nSources:\n" + "\n".join(
                    f"[{s['n']}] {s.get('title', '')}" + (f" — {s['source']}" if s.get("source") else "")
                    + (f", {s['fetched_at']}" if s.get("fetched_at") else "") for s in draft.sources)
        trace = [{"agent": n, "bid": plan["bids"].get(n), "status": f.status, "ms": f.ms, "reason": f.reason}
                 for n, f in board.findings.items()]
        yield {"type": "final", "result": self._finish(task, sid, outcome, text, draft, trace, issues, plan, t0,
                                                      board=board)}

    def _run_fallback(self, task: Task, board: Blackboard) -> Finding:
        a = self.fallback
        t0 = time.time()
        try:
            f = a.run(task, board)
        except Exception as e:
            f = Finding(agent=a.name, status=ERROR, reason=f"{type(e).__name__}: {e}")
        f.agent, f.ms = a.name, int((time.time() - t0) * 1000)
        return f

    def _finish(self, task, sid, outcome, text, draft, trace, issues, plan, t0, board=None, guardrail=None):
        ms = int((time.time() - t0) * 1000)
        slots = {}
        if board is not None:
            for f in board.ok():
                slots.update({k: v for k, v in (f.facts.get("_slots") or {}).items()})
        slots.update({k: task.ctx.get(k) for k in ("subject",) if task.ctx.get(k)})
        self.sessions.remember(sid, task.question, text, slots)
        if self.episodic is not None:
            self.episodic.record(sid, task.question, outcome, text, trace, ms)
        return {
            "session_id": sid,
            "outcome": outcome,
            "answer": text,
            "headline": draft.headline if draft else "",
            "sections": [{"agent": a, "lines": ls} for a, ls in (draft.sections if draft else [])],
            "sources": draft.sources if draft else [],
            "findings": [f.to_dict() for f in (board.findings.values() if board else [])],
            "plan": plan,
            "trace": trace,
            "critique": issues,
            "guardrail": guardrail,
            "ms": ms,
        }


def _prune_sources(draft: "Draft") -> None:
    """After the critics: drop sources no remaining line cites, renumber the rest."""
    if not draft.sources:
        return
    cited = {int(n) for _, ls in draft.sections for ln in ls for n in re.findall(r"\[(\d+)\]", ln)}
    keep = [s for s in draft.sources if s.get("n") in cited]
    if len(keep) == len(draft.sources):
        return
    remap = {s["n"]: i + 1 for i, s in enumerate(keep)}
    draft.sources = [{**s, "n": remap[s["n"]]} for s in keep]
    draft.sections = [(a, [re.sub(r"\[(\d+)\]", lambda m: f"[{remap.get(int(m.group(1)), m.group(1))}]", ln)
                           for ln in ls]) for a, ls in draft.sections]


def _norm_sentence(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\[\d+\]", "", s)).strip().lower()


def _unsaid(lines: List[str], said: set) -> List[str]:
    """Drop sentences another specialist already stated (two agents reading the
    same source must not say it twice); keep headers and short lines."""
    out = []
    for ln in lines:
        parts = re.split(r"(?<=[.!?])\s+(?=\S)", ln)
        keep = []
        for p in parts:
            key = _norm_sentence(p)
            if len(key) >= 30 and key in said:
                continue
            if len(key) >= 30:
                said.add(key)
            keep.append(p)
        joined = " ".join(keep).strip()
        if joined and not (re.fullmatch(r"(\s*\[\d+\])+", joined)):
            out.append(joined)
    return out


def sse(events: Iterator[Dict[str, Any]], heartbeat: bool = True) -> Iterator[str]:
    """Format run_stream() events as Server-Sent Events for a streaming HTTP
    response (Flask: Response(stream_with_context(sse(...)), mimetype="text/event-stream"))."""
    if heartbeat:
        yield ": stream open\n\n"
    for ev in events:
        yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items() if not str(k).startswith("_")}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, (str, int, bool)) or x is None:
        return x
    return str(x)
