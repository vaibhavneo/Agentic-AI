"""Quant Lab specialists for the desk's AI Chat team (mas/converse/assistant_team.py).

    quant_portfolio   "how risky is my portfolio", "optimize my holdings", "what could it be worth in
                      10 years with $500 a month" — risk, optimizer and projection (quant/portfolio.py)
                      over the holdings the screen sends (they live in the user's browser)
    quant_signals     "any intraday setups?", "VWAP setups on TSLA" — the scanner's latest-session
                      signals (quant/live.py), each with its rule's own 60-session record

Every number comes from the quant modules and is cited to them; the
optimizer is labelled in-sample, the projection a range, the signals
paper-tracked research. Nothing here places an order.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import agent_core as ac

PORTFOLIO = re.compile(r"\b(my|our|this|the)\s+(portfolio|holdings|positions|book|allocation|stocks)\b", re.I)
RISK = re.compile(r"\b(risk|risky|volatil\w*|var|value at risk|drawdowns?|beta|correlat\w*|diversif\w*|concentrat\w*)\b", re.I)
OPTIMIZE = re.compile(r"\b(optimi[sz]\w*|rebalanc\w*|allocat\w*|weights?|weighting|min(imum)?[- ]variance|sharpe|"
                      r"risk[- ]parity|efficient frontier)\b", re.I)
PROJECT = re.compile(r"\b(project\w*|in \d+ years?|retire\w*|grow|growth|be worth|future value|goal|monte carlo|"
                     r"long[- ]term|\d+ years? from now)\b", re.I)
SIGNALS = re.compile(r"\b(intraday|setups?|signals?|breakouts?|breakdowns?|vwap|rsi|gap[- ]and[- ]go|gappers?|"
                     r"day[- ]?trad\w*|scalp\w*|opening[- ]range|orb)\b", re.I)


def _usd(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


def holdings_from(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """{symbol|ticker, shares|value} rows from the screen; anything else is ignored."""
    out = []
    for h in (ctx.get("holdings") or [])[:40]:
        if not isinstance(h, dict):
            continue
        sym = str(h.get("symbol") or h.get("ticker") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-^=]{1,10}", sym):
            continue
        try:
            if h.get("value") is not None and float(h["value"]) > 0:
                out.append({"symbol": sym, "value": float(h["value"])})
            elif float(h.get("shares") or 0) > 0:
                out.append({"symbol": sym, "shares": float(h["shares"])})
        except (TypeError, ValueError):
            continue
    return out


RULE_WORDS = {"VWAP", "RSI", "ORB", "GAP", "GAPS", "R", "ET", "ANY", "ON", "TODAY", "DAY"}


def named_symbols(question: str) -> List[str]:
    """Tickers the question names — not the setup words that look like one."""
    from .symbols import extract
    return [x for x in ((extract(question) or {}).get("symbols") or []) if x and x.upper() not in RULE_WORDS][:3]


ASKS_FOR_SETUPS = re.compile(r"\b(setups?|signals?|any|today|now|right now|scan\w*|firing|trigger\w*|gappers?|"
                             r"trades?|ideas?|plays?|levels?)\b", re.I)


def wants_signals(question: str) -> bool:
    """Today's setups, not the concept: "any VWAP setups?" or "breakouts on TSLA",
    but "what is VWAP?" is a definition for the desk and the web."""
    q = question or ""
    return bool(SIGNALS.search(q) and (ASKS_FOR_SETUPS.search(q) or named_symbols(q)))


def is_personal(question: str) -> bool:
    """A question about the user's own portfolio (its write-up stays on a local model)."""
    return bool(PORTFOLIO.search(question or ""))


def _projection_params(q: str) -> Dict[str, Any]:
    p: Dict[str, Any] = {}
    m = re.search(r"\b(\d{1,2})\s*(?:years?|yrs?)\b", q, re.I)
    if m and 1 <= int(m.group(1)) <= 40:
        p["years"] = int(m.group(1))
    m = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)\s*(k)?\s*(?:a|per|each|every|/)\s*month", q, re.I)
    if m:
        p["monthly_contribution"] = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
    m = re.search(r"\b(?:reach|hit|get to|goal of|target of)\s*\$?\s*([\d,]+(?:\.\d+)?)\s*(k|m|million)?", q, re.I)
    if m:
        mult = {"k": 1e3, "m": 1e6, "million": 1e6}.get((m.group(2) or "").lower(), 1)
        p["goal"] = float(m.group(1).replace(",", "")) * mult
    return p


class QuantPortfolioAgent(ac.Agent):
    name, role, priority, timeout_s = "quant_portfolio", "portfolio risk, optimizer and long-term projection", 5, 30.0

    def bid(self, task):
        q = task.question
        if not (PORTFOLIO.search(q) or task.ctx.get("holdings") and re.search(r"\bportfolio\b", q, re.I)):
            return 0.0
        return 0.95 if (RISK.search(q) or OPTIMIZE.search(q) or PROJECT.search(q)) else 0.0

    def run(self, task, board):
        from quant import portfolio as Q
        q = task.question
        holdings = holdings_from(task.ctx)
        if not holdings:
            return self.finding(lines=["I need your holdings to measure that. Add them in the ⚡ Quant Lab (or 💼 My "
                                       "Portfolio) — they stay in your browser and come along with your questions."],
                                facts={"needs": "holdings"})
        lines: List[str] = []
        facts: Dict[str, Any] = {}
        sources: List[Dict[str, Any]] = []
        want_opt, want_proj = bool(OPTIMIZE.search(q)), bool(PROJECT.search(q))
        want_risk = bool(RISK.search(q)) or not (want_opt or want_proj)
        if want_risk:
            r = Q.risk(holdings)
            p, top = r["portfolio"], max(r["holdings"], key=lambda h: h["risk_share"])
            sources.append({"n": 1, "title": f"Quant Lab risk model — {r['window']}", "source": "Yahoo Finance daily "
                            "adjusted closes", "url": "/quant", "fetched_at": r["as_of"]})
            lines += [
                f"Your portfolio ({_usd(r['total_value'])} across {len(r['holdings'])} holdings) has run at "
                f"{_pct(p['vol_ann'])} annual volatility with a beta of {p['beta']} to the S&P 500 [1].",
                f"On a 1-in-20 bad day it has lost {_pct(p['var95_1d'], 2)} or more — about {_usd(p['var95_1d_usd'])} at "
                f"today's value; the worst 5% of days averaged {_pct(-p['cvar95_1d'], 2)} [1].",
                f"{top['symbol']} is {_pct(top['weight'])} of the money but {_pct(top['risk_share'])} of the risk"
                + (f"; the most correlated pair is {r['most_correlated_pair']['a']} & {r['most_correlated_pair']['b']} "
                   f"({r['most_correlated_pair']['corr']:.2f})" if r.get("most_correlated_pair") else "") + " [1].",
                f"Worst peak-to-trough fall in the window: {_pct(p['max_drawdown'])} [1].",
            ]
            facts["risk"] = {"vol_ann": p["vol_ann"], "beta": p["beta"], "var95_1d_usd": p["var95_1d_usd"]}
        if want_opt:
            n = len(sources) + 1
            res = {m: Q.optimize([h["symbol"] for h in holdings], m) for m in ("min_variance", "risk_parity", "max_sharpe")}
            sources.append({"n": n, "title": f"Quant Lab optimizer — {res['min_variance']['window']}, in-sample",
                            "source": "Yahoo Finance daily adjusted closes", "url": "/quant",
                            "fetched_at": res["min_variance"]["as_of"]})
            names = {"min_variance": "Minimum-variance", "risk_parity": "Risk parity", "max_sharpe": "Max-Sharpe"}
            for m, o in res.items():
                w = ", ".join(f"{s} {_pct(x, 0)}" for s, x in list(o["weights"].items())[:6])
                lines.append(f"{names[m]} would hold {w} — volatility {_pct(o['vol_ann'])} [{n}].")
            rb = Q.rebalance(holdings, res["risk_parity"]["weights"])
            if rb["trades"]:
                moves = "; ".join(f"{t['action']} {t['symbol']} {_usd(abs(t['usd']))}" for t in rb["trades"][:5])
                lines.append(f"To reach risk parity: {moves} (turnover {_pct(rb['turnover'])}) [{n}].")
            lines.append("These weights come from the last 3 years of prices (in-sample), so they are a comparison, not "
                         "advice; the ⚡ Quant Lab shows every method side by side.")
            facts["optimize"] = {m: o["weights"] for m, o in res.items()}
        if want_proj:
            n = len(sources) + 1
            pp = _projection_params(q)
            pr = Q.project(holdings, **pp)
            P = pr["percentiles"]
            sources.append({"n": n, "title": f"Quant Lab projection — {pr['paths']:,} block-bootstrap paths, history "
                            f"{pr['history']}", "source": "Yahoo Finance daily adjusted closes", "url": "/quant"})
            add = f" with {_usd(pr['monthly_contribution'])} a month" if pr["monthly_contribution"] else ""
            lines += [
                f"Over {pr['years']} years{add}, the median simulated path ends at {_usd(pr['median_end'])} — 90% of "
                f"paths between {_usd(P[5][-1])} and {_usd(P[95][-1])} — against {_usd(pr['invested'])} put in [{n}].",
                f"Chance of ending below what you put in: {_pct(pr['prob_loss'], 0)}"
                + (f"; of reaching {_usd(pr['goal'])}: {_pct(pr['prob_goal'], 0)}" if pr.get("goal") else "") + f" [{n}].",
                f"It assumes a {_pct(pr['expected_return'], 0)} average year (typical compounded growth "
                f"{_pct(pr['typical_growth_ann'])} at this volatility); the window itself returned "
                f"{_pct(pr['hist_return_ann'])} a year, which is not assumed to repeat [{n}].",
            ]
            facts["project"] = {"median_end": pr["median_end"], "prob_loss": pr["prob_loss"]}
        return self.finding(lines=lines, sources=sources, facts=facts)


class QuantSignalsAgent(ac.Agent):
    name, role, priority, timeout_s = "quant_signals", "intraday setups from the scanner, with each rule's record", 6, 30.0

    def bid(self, task):
        return 0.9 if wants_signals(task.question) else 0.0

    def run(self, task, board):
        from quant import live as QL
        syms = named_symbols(task.question)
        res = QL.scan_all(syms or None)
        sigs = res["signals"]
        rule_q = [r for r, rx in (("vwap", r"vwap"), ("rsi", r"\brsi\b"), ("orb", r"breakout|breakdown|opening[- ]range|\borb\b"),
                                  ("gap", r"\bgap")) if re.search(rx, task.question, re.I)]
        if rule_q:
            sigs = [s for s in sigs if any(s["rule"].startswith(r) for r in rule_q)]
        day = (res["as_of"] or "")[:10]
        src = [{"n": 1, "title": f"Quant Lab intraday scanner — 5-minute bars, session {day}", "source": "Yahoo Finance "
                "chart API", "url": "/quant", "fetched_at": res["as_of"]}]
        scope = ", ".join(syms) if syms else f"the {len(res['symbols'])}-name scan list"
        record = f"across the {len(QL.SCAN)}-name scan list " if syms else ""
        lines: List[str] = []
        if not sigs:
            lines.append(f"No matching setups on {scope} in the {day} session [1].")
        else:
            lines.append(f"Latest setups on {scope} ({day} session) [1]:")
            for s in sigs[:5]:
                lines.append(f"- {s['symbol']} {s['label']} at {s['ts'][11:16]} ET: entry ${s['entry']:,.2f}, stop "
                             f"${s['stop']:,.2f}, 2R target ${s['target']:,.2f}"
                             + (f", {s['rvol']:.1f}× normal volume" if s.get("rvol") else "") + " [1].")
        bt = res["backtest"]
        edge = [(k, v) for k, v in bt.items() if v["avg_r"] > 0 and (v.get("t_stat") or 0) >= 2]
        best = max(bt.items(), key=lambda kv: kv[1]["avg_r"]) if bt else None
        if bt:
            if edge:
                lines.append(f"Rules with a measured edge {record}over the last ~60 sessions: " + "; ".join(
                    f"{QL.LABEL[k]} {v['avg_r']:+.2f}R over {v['n']} trades" for k, v in edge) + " [1].")
            else:
                lines.append(f"None of the rules has shown an edge {record}over the last ~60 sessions (best: {QL.LABEL[best[0]]} "
                             f"{best[1]['avg_r']:+.2f}R over {best[1]['n']} trades"
                             + (f", t-stat {best[1]['t_stat']}" if best[1].get("t_stat") is not None else "") + ") — "
                             f"treat these as watch-list levels, not trades [1].")
        lines.append("Signals are paper-tracked research in the ⚡ Quant Lab journal; nothing here places an order.")
        return self.finding(lines=lines, sources=src, facts={"signals": len(sigs), "edge_rules": [k for k, _ in edge]})
