"""
Stock Analysis Agent — fundamental analysis from what the company filed.

Statements, earnings quality, the filings' own disclosures, peers, valuation
and price context (stock_analysis/report.py). Equities only: an ETF, a coin or
a currency files no 10-K, and declining with that reason is the right answer.
No LLM writes a number here; the optional MD&A summary is held to the filing.
"""
from __future__ import annotations

from typing import Tuple

from ..contract import AgentRequest, AgentResult, error, ok, unavailable

AGENT_ID = "stock_analysis"
CAPABILITY = "fundamental_analysis"


def available(symbol: str, asset_class: str) -> Tuple[bool, str]:
    if asset_class != "EQUITY":
        return False, (f"fundamental analysis reads a company's SEC filings; a {asset_class.lower()} "
                       "files no 10-K or 20-F")
    return True, ""


def run(request: AgentRequest) -> AgentResult:
    if not request.symbol:
        return unavailable(AGENT_ID, request.capability, "fundamental analysis needs a symbol")
    try:
        from stock_analysis.report import build_report
        p = request.params or {}
        rep = build_report(request.symbol, as_of=p.get("as_of"), include=p.get("sections"),
                           peers_override=p.get("peers"), mdna_summary=bool(p.get("mdna_summary")))
        if not rep.get("available"):
            return unavailable(AGENT_ID, request.capability,
                               rep.get("reason") or f"{request.symbol} has no SEC financial statements")
        return ok(AGENT_ID, request.capability, rep, price_basis="TRADED_PRICE", source="sec-edgar")
    except Exception as e:
        return error(AGENT_ID, request.capability, e)
