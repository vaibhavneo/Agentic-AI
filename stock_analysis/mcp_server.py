"""
The desk's stock analysis as an MCP server (Model Context Protocol, Streamable
HTTP transport, JSON responses) — so Claude Code, Claude Desktop or any MCP
client can call the same analysis the web UI shows:

  claude mcp add --transport http stock-desk https://<host>/mcp
      [--header "Authorization: Bearer $MCP_TOKEN"]

Tools are READ-ONLY: they read filings, prices and the desk's own stored
state; none changes the watchlist, marks alerts, places orders or spends LLM
credit (the MD&A / call summaries are not offered here). When MCP_TOKEN is set
every request must carry it as a bearer token; unset, the endpoint is as open
as the REST API it mirrors.

`handle(message)` is pure JSON-RPC 2.0 (no Flask) so it is tested directly;
web/app.py's /mcp route is a thin wrapper.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "stock-analysis-desk", "version": "1.0.0"}
INSTRUCTIONS = ("Fundamental analysis from SEC filings (10-K/10-Q/20-F/8-K): earnings quality, filing red flags, "
                "valuation, peers, price context, analyst/insider activity, guidance, segments and a fundamentals "
                "score. Every figure carries its filing source. Use as_of=YYYY-MM-DD for a point-in-time read. "
                "prediction_scorecard says how the desk's past calls actually did against prices and SPY — "
                "quote its verdicts and independent-window counts, not just hit rates. "
                "Scores are context, not recommendations.")

_TICKER = re.compile(r"^[A-Za-z0-9.\-^=]{1,12}$")
_SECTIONS = ("statements", "quality", "filings", "valuation", "peers", "technicals", "street", "guidance",
             "segments", "transcript", "score")
DEFAULT_SECTIONS = ["quality", "filings", "valuation", "technicals", "street", "guidance", "segments", "score"]
MAX_COMPARE = 25

_RO = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}


class InvalidParams(ValueError):
    pass


def _ticker(v: Any, field: str = "ticker") -> str:
    if not isinstance(v, str) or not _TICKER.match(v):
        raise InvalidParams(f"{field} must be a ticker symbol")
    return v.upper()


def _as_of(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    try:
        datetime.strptime(str(v)[:10], "%Y-%m-%d")
    except ValueError:
        raise InvalidParams("as_of must be YYYY-MM-DD")
    return str(v)[:10]


def _num(args: Dict[str, Any], k: str) -> Optional[float]:
    v = args.get(k)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise InvalidParams(f"{k} must be a number")
    return float(v)


# ── tools ─────────────────────────────────────────────────────────────────────

def tool_stock_analysis(args: Dict[str, Any]) -> Dict[str, Any]:
    from .report import build_report
    sym = _ticker(args.get("ticker"))
    sections = args.get("sections") or DEFAULT_SECTIONS
    if not isinstance(sections, list) or any(s not in _SECTIONS for s in sections):
        raise InvalidParams(f"sections must be a list from {list(_SECTIONS)}")
    peers = args.get("peers")
    if peers is not None:
        if not isinstance(peers, list) or len(peers) > 12:
            raise InvalidParams("peers must be a list of up to 12 tickers")
        peers = [_ticker(p, "peers") for p in peers]
    return build_report(sym, as_of=_as_of(args.get("as_of")), include=list(sections), peers_override=peers,
                        mdna_summary=False)


def tool_compare_fundamentals(args: Dict[str, Any]) -> Dict[str, Any]:
    from .sweep import red_flags, sweep
    tickers = args.get("tickers")
    if not isinstance(tickers, list) or not tickers or len(tickers) > MAX_COMPARE:
        raise InvalidParams(f"tickers must be a list of 1-{MAX_COMPARE} symbols")
    reads = sweep([_ticker(t, "tickers") for t in tickers], as_of=_as_of(args.get("as_of")))
    return {"available": True, "reads": reads, "red_flags": red_flags(reads)}


def tool_screener(args: Dict[str, Any]) -> Dict[str, Any]:
    from .screener import CAVEAT, latest, screen
    grades = args.get("grades")
    if grades is not None and (not isinstance(grades, list) or any(g not in "ABCDF" or not g for g in grades)):
        raise InvalidParams("grades must be a list from A, B, C, D, F")
    sort = args.get("sort") or "score"
    if not isinstance(sort, str):
        raise InvalidParams("sort must be a field name")
    limit = args.get("limit", 50)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise InvalidParams("limit must be an integer 1-500")
    snap = latest()
    if not snap:
        return {"available": False, "caveat": CAVEAT,
                "reason": "the screener has not been built yet — the desk's maintenance scheduler builds it"}
    rows = screen(snap["rows"], min_score=_num(args, "min_score"), grades=grades, max_pe=_num(args, "max_pe"),
                  min_fcf_yield=_num(args, "min_fcf_yield"), no_filing_concerns=bool(args.get("no_filing_concerns")),
                  min_revenue_growth=_num(args, "min_revenue_growth"), sort=sort,
                  descending=not args.get("ascending"), limit=limit)
    return {"available": True, "generated_at": snap["generated_at"], "universe": snap["n"], "rows": rows,
            "caveat": CAVEAT}


def tool_filing_alerts(args: Dict[str, Any]) -> Dict[str, Any]:
    from .watcher import alerts
    limit = args.get("limit", 50)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise InvalidParams("limit must be an integer 1-500")
    rows = alerts(limit=limit, unread_only=bool(args.get("unread_only")))
    return {"available": True, "alerts": rows, "unread": sum(1 for r in rows if not r.get("read"))}


def tool_watchlist(args: Dict[str, Any]) -> Dict[str, Any]:
    from .watcher import watched
    return {"available": True, "watched": watched()}


_EVAL_HORIZONS = (1, 5, 20, 60, 126, 252)


def tool_prediction_scorecard(args: Dict[str, Any]) -> Dict[str, Any]:
    from evaluation.report import DEFAULT_HORIZONS, build
    hs = args.get("horizons") or list(DEFAULT_HORIZONS)
    if not isinstance(hs, list) or not hs or any(h not in _EVAL_HORIZONS for h in hs):
        raise InvalidParams(f"horizons must be a list drawn from {list(_EVAL_HORIZONS)}")
    source = args.get("source", "live")
    if source not in ("live", "all", "replay"):
        raise InvalidParams("source must be live, all or replay")
    rep = build(tuple(int(h) for h in hs), source)
    if not args.get("detail"):
        # The headline, verdicts and coverage answer "how good are the calls";
        # the per-week trend and reliability bins are opt-in.
        rep = {"available": True, "generated_at": rep["generated_at"], "source": rep["source"],
               "rules": rep["rules"], "headline": rep["headline"],
               "horizons": {h: {"coverage": c["coverage"], "verdicts": c["verdicts"],
                                "ranking": c["ranking"], "direction": {k: v for k, v in c["direction"].items()
                                                                       if k != "by_action"},
                                "p_up": {k: v for k, v in c["p_up"].items() if k != "reliability"},
                                "confidence": c["confidence"],
                                "challengers": {n: {"verdict": v["verdict"],
                                                    "challenger_rank_ic": v["challenger_rank_ic"]["mean"],
                                                    "desk_rank_ic_same_names": v["composite_rank_ic_same_names"]["mean"]}
                                                for n, v in (c.get("challengers") or {}).items()},
                                "paper": {k: v for k, v in (c.get("paper") or {}).items() if k != "curve"}}
                            for h, c in rep["horizons"].items()},
               "feedback": rep["feedback"]}
    return dict(rep, available=True)


def _schema(props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_AS_OF = {"type": "string", "description": "YYYY-MM-DD: use only what had been filed by this date"}
_TICKER_S = {"type": "string", "description": "Ticker, e.g. NVDA, BRK-B, TSM (ADRs and 20-F filers included)"}

TOOLS: Dict[str, Dict[str, Any]] = {
    "stock_analysis": {
        "fn": tool_stock_analysis,
        "title": "Stock analysis report",
        "description": ("Fundamental report for one company from its SEC filings: earnings quality (cash "
                        "conversion, accruals, Beneish M, Piotroski F, Altman Z, dilution), filing red flags "
                        "(8-K items, late filings, material weaknesses, going concern, auditor changes), valuation "
                        "and reverse DCF, peers, price trend and earnings reactions, analyst/insider activity, "
                        "guidance and its track record, segments, and the fundamentals score. Sections default to "
                        "everything except the raw statements, peers and the call transcript."),
        "inputSchema": _schema({
            "ticker": _TICKER_S, "as_of": _AS_OF,
            "sections": {"type": "array", "items": {"type": "string", "enum": list(_SECTIONS)},
                         "description": "Limit the work to these sections"},
            "peers": {"type": "array", "items": {"type": "string"}, "maxItems": 12,
                      "description": "Name the peer set instead of same-industry SEC filers"}}, ["ticker"]),
    },
    "compare_fundamentals": {
        "fn": tool_compare_fundamentals,
        "title": "Compare fundamentals",
        "description": ("The compact fundamentals read (score, earnings-quality grade, filing concerns) for up to "
                        f"{MAX_COMPARE} tickers at once, with the names that need a look first."),
        "inputSchema": _schema({"tickers": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                                            "maxItems": MAX_COMPARE}, "as_of": _AS_OF}, ["tickers"]),
    },
    "screener": {
        "fn": tool_screener,
        "title": "Fundamentals screener",
        "description": ("Filter the desk's watched universe on computed fundamentals (refreshed by its scheduler). "
                        "A filter, not a recommendation."),
        "inputSchema": _schema({
            "min_score": {"type": "number"}, "grades": {"type": "array", "items": {"type": "string",
                                                                                   "enum": list("ABCDF")}},
            "max_pe": {"type": "number"}, "min_fcf_yield": {"type": "number", "description": "fraction, 0.04 = 4%"},
            "min_revenue_growth": {"type": "number", "description": "fraction, year over year"},
            "no_filing_concerns": {"type": "boolean"},
            "sort": {"type": "string", "description": "score, pe, fcf_yield, revenue_growth, quality_score…"},
            "ascending": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
    },
    "filing_alerts": {
        "fn": tool_filing_alerts,
        "title": "Filing alerts",
        "description": ("New filings on watched names the desk flagged (restatements, auditor changes, late "
                        "filings, bankruptcy, new 10-Q/10-K with the score move), most severe first."),
        "inputSchema": _schema({"unread_only": {"type": "boolean"},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
    },
    "prediction_scorecard": {
        "fn": tool_prediction_scorecard,
        "title": "Prediction scorecard",
        "description": ("How the desk's past calls actually did: ranking skill against SPY (same-day rank IC, "
                        "bullish-minus-bearish spread), hit rate on price and against SPY, whether p_up beat "
                        "always-50% and the base rate known at the time, and whether confidence labels delivered "
                        "what they claimed — per horizon, with overlap-corrected t-stats, independent-window "
                        "counts and a verdict (EDGE / PROMISING / NO_EDGE / ADVERSE / INSUFFICIENT). Also: the desk "
                        "against simple models on the same names and days (12-1 momentum, reversal, low volatility, "
                        "single pillars), and a paper portfolio of its top third after trading costs."),
        "inputSchema": _schema({
            "horizons": {"type": "array", "items": {"type": "integer", "enum": list(_EVAL_HORIZONS)},
                         "description": "Trading-day horizons (default 1, 5, 20, 60)"},
            "source": {"type": "string", "enum": ["live", "all", "replay"],
                       "description": "live = calls the desk made (default); replay = point-in-time backfill"},
            "detail": {"type": "boolean", "description": "Include per-week trend, reliability bins, pillars"}}),
    },
    "watchlist": {
        "fn": tool_watchlist,
        "title": "Watched names",
        "description": "The tickers the filing watcher and screener follow.",
        "inputSchema": _schema({}),
    },
}


def tool_list() -> List[Dict[str, Any]]:
    return [{"name": n, "title": t["title"], "description": t["description"], "inputSchema": t["inputSchema"],
             "annotations": dict(_RO, title=t["title"])} for n, t in TOOLS.items()]


# ── JSON-RPC ──────────────────────────────────────────────────────────────────

def _err(mid: Any, code: int, msg: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def _ok(mid: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def call_tool(name: str, args: Dict[str, Any], tools: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Run one tool. A failure inside the tool is a RESULT with isError (the
    model can read and react to it); bad arguments raise InvalidParams."""
    fn: Callable[[Dict[str, Any]], Dict[str, Any]] = (tools or TOOLS)[name]["fn"]
    try:
        out = fn(args)
    except InvalidParams:
        raise
    except Exception as e:
        return {"content": [{"type": "text", "text": f"{name} failed: {type(e).__name__}: {e}"}], "isError": True}
    failed = isinstance(out, dict) and out.get("available") is False
    text = json.dumps(out, default=str)
    return {"content": [{"type": "text", "text": text}], "structuredContent": json.loads(text), "isError": failed}


def handle(msg: Any, tools: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """One JSON-RPC message -> its response, or None for a notification."""
    tools = tools or TOOLS
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid JSON-RPC request")
    method, mid, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if "id" not in msg:                       # notification (notifications/initialized, cancelled…)
        return None
    if not isinstance(params, dict):
        return _err(mid, -32602, "params must be an object")
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _ok(mid, {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": [t for t in tool_list() if t["name"] in tools]})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in tools:
            return _err(mid, -32602, f"unknown tool: {name}")
        if not isinstance(args, dict):
            return _err(mid, -32602, "arguments must be an object")
        try:
            return _ok(mid, call_tool(name, args, tools))
        except InvalidParams as e:
            return _err(mid, -32602, str(e))
    return _err(mid, -32601, f"method not found: {method}")
