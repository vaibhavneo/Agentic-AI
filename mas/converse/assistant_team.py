"""
The desk's AI Chat team — the full desk plus web research, under the shared
orchestrator (mas/converse/agent_core.py), then grounded synthesis
(mas/converse/assistant.py).

    question ─► guardrails (the desk won't pick names; no orders)
            ─► quant  the quant lab (mas/converse/quant_agents.py): the user's portfolio risk, optimizer
                      and projection; the intraday scanner's setups with each rule's record
            ─► desk   the whole multi-agent desk (mas.converse.turn): research,
                      options, regime, the live market, its knowledge layer
            ─► web    web research in parallel: search results and the top
                      pages, cited (mas/converse/knowledge.py, web only)
            ─► the composed, cited research ─► (model available) a write-up
               of that research, every number checked against it
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import agent_core as ac
from . import quant_agents


class DeskAgent(ac.Agent):
    name, role, priority, timeout_s = "desk", "the full desk: research, options, regime, live market, knowledge", 10, 75.0

    def bid(self, task):
        # "Any intraday setups?" names no stock: that is the scanner's, and the
        # desk would only answer it with a web snippet about setups in general.
        if quant_agents.wants_signals(task.question) and not quant_agents.named_symbols(task.question):
            return 0.0
        return 0.9

    def run(self, task, board):
        from . import turn
        # The screen's holdings (shares only) reach the desk's portfolio review too.
        held = [{"ticker": h["symbol"], "shares": h["shares"]} for h in quant_agents.holdings_from(task.ctx)
                if h.get("shares")]
        out = turn(task.question, session_id=task.ctx.get("desk_session"), holdings=held or None)
        reply = out.get("reply") or {}
        kind = reply.get("kind")
        lines: List[str] = []
        sources: List[Dict[str, Any]] = []
        for b in reply.get("blocks") or []:
            if b.get("sources"):
                # The knowledge block's citations go to the orchestrator, which
                # renumbers every agent's sources into one list.
                offset = len(sources)
                for src in b["sources"]:
                    sources.append({**src, "n": src["n"] + offset})
                for ln in b.get("lines") or []:
                    if ln and not ln.startswith("Sources:"):
                        lines.append(re.sub(r"\[(\d+)\]", lambda m: f"[{int(m.group(1)) + offset}]", ln))
                continue
            lines += [ln for ln in (b.get("lines") or []) if ln]
        sid = (out.get("session") or {}).get("session_id")
        if kind in ("UNROUTABLE", "SMALL_TALK", "CAPABILITY_QUESTION", "EMPTY") or \
                (kind == "NEEDS_SUBJECT" and not lines):
            return ac.Finding(agent=self.name, status=ac.DECLINED, reason=f"the desk had no specialist for it ({kind})",
                              facts={"_slots": {"desk_session": sid}})
        ran = sorted({t.get("capability") for t in out.get("trace", []) if t.get("status") == "OK"} - {None})
        return self.finding(lines=lines, sources=sources,
                            facts={"_slots": {"desk_session": sid}, "desk_kind": kind, "specialists": ran})


class WebResearchAgent(ac.Agent):
    name, role, priority, timeout_s = "web", "web research: search results and the top pages, cited", 40, 25.0
    yields_to = ("quant_portfolio", "quant_signals")      # the user's own portfolio / today's setups aren't web questions

    def bid(self, task):
        from .knowledge import lk
        t = task.question
        if re.fullmatch(r"\s*\$?[A-Za-z.\-=^]{1,10}\s*", t):
            return 0.0                                    # a bare ticker is the desk's
        return 0.6 if len(lk.terms(t)) >= 2 else 0.0

    def run(self, task, board):
        from .knowledge import lk, pipeline
        from .symbols import extract
        syms = (extract(task.question) or {}).get("symbols") or []
        # Its own shelf: web results only, so it adds to the desk instead of
        # repeating the encyclopedia sentence the desk already quoted.
        shelf = lk.Pipeline(pipeline().store, [lk.WebSearchFetcher(top=5, pages=2)], kinds=("web",))
        k = shelf.answer(task.question, {"tickers": syms[:2]}, force_live=False)
        if not k.get("found"):
            return self.decline("the web search found nothing relevant")
        return self.finding(lines=[k["answer"]], sources=k.get("sources") or [])


class DeskGuardrail(ac.Guardrail):
    """The desk's own refusals, before any research: it does not pick names
    for you, and it cannot place orders."""
    name = "desk_rules"
    ORDERS = re.compile(r"\b(buy|sell|short)\b.{0,40}\b(for me|on my behalf|now)\b|\bplace (an? )?(order|trade)\b", re.I)

    def check(self, task):
        from .intent import parse
        p = parse(task.question)
        if (p.get("clarification") or "").startswith("I do not pick names"):
            return (ac.REFUSED, p["clarification"])
        if self.ORDERS.search(task.question):
            return (ac.REFUSED, "I can't place orders — this desk researches; it has no broker connection. Ask for "
                                "the read on a name instead, e.g. \"should I buy NVDA?\" or \"what's the case for AAPL?\"")
        return None


_sessions = ac.SessionMemory()


def build() -> ac.Orchestrator:
    return ac.Orchestrator([quant_agents.QuantPortfolioAgent(), quant_agents.QuantSignalsAgent(), DeskAgent(),
                            WebResearchAgent()], guardrails=[DeskGuardrail()],
                           critics=[ac.ForbiddenClaimsCritic()], threshold=0.5, max_agents=3, budget_s=90,
                           session_memory=_sessions,
                           empty_text="Neither the desk nor a web search had an answer for that. Try naming a "
                                      "symbol, or ask about the market, a concept, or the news.")


def run_stream(question: str, session_id: Optional[str] = None, holdings: Optional[List[Dict[str, Any]]] = None):
    return build().run_stream(question, {"holdings": holdings} if holdings else None, session_id=session_id)


APP_DESCRIPTION = ("the Stock Desk — a multi-agent stock research desk (research reads, options structures, market "
                   "regime, live market data, SEC filings fundamentals, a quant lab for portfolio risk, optimization, "
                   "projections and intraday signals) plus web research")
