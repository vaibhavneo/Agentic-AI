"""
The /mcp endpoint (stock_analysis/mcp_server.py + web/app.py) — offline.

Run: python3 tests/test_mcp_server.py

Checks the MCP handshake, that every tool is read-only and schema-described,
that bad arguments are protocol errors while tool failures are readable
results, and the transport guards (bearer token, cross-site Origin,
notifications, GET).
"""
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["STOCK_ANALYSIS_STATE_DIR"] = tempfile.mkdtemp()

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {name:62s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    assert cond, name


def _rpc(method, params=None, mid=1):
    m = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        m["params"] = params
    return m


def test_handshake_and_tools():
    print("=== 1. handshake and tool list ===")
    from stock_analysis.mcp_server import handle
    r = handle(_rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                   "clientInfo": {"name": "t", "version": "0"}}))
    check("negotiates the client's supported version", r["result"]["protocolVersion"] == "2025-03-26")
    check("advertises tools", "tools" in r["result"]["capabilities"])
    r = handle(_rpc("initialize", {"protocolVersion": "1999-01-01"}))
    check("unknown version -> the server's latest", r["result"]["protocolVersion"] == "2025-06-18")
    tools = handle(_rpc("tools/list"))["result"]["tools"]
    names = {t["name"] for t in tools}
    check("the six read-only tools", names == {"stock_analysis", "compare_fundamentals", "screener",
                                               "filing_alerts", "watchlist", "prediction_scorecard"},
          sorted(names))
    check("every tool is marked read-only", all(t["annotations"]["readOnlyHint"] for t in tools))
    check("every tool has an object input schema", all(t["inputSchema"]["type"] == "object" for t in tools))
    check("no tool can change state", not any(w in n for n in names for w in ("add", "remove", "mark", "order",
                                                                               "trade", "refresh")))
    check("notification -> no response", handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None)
    check("ping", handle(_rpc("ping"))["result"] == {})
    check("unknown method -> -32601", handle(_rpc("resources/list"))["error"]["code"] == -32601)
    check("not JSON-RPC -> -32600", handle({"id": 1, "method": "x"})["error"]["code"] == -32600)


def test_tool_calls():
    print("=== 2. tool calls ===")
    from stock_analysis import mcp_server as m
    r = m.handle(_rpc("tools/call", {"name": "stock_analysis", "arguments": {"ticker": "NV DA;"}}))
    check("bad ticker -> -32602, nothing fetched", r["error"]["code"] == -32602)
    r = m.handle(_rpc("tools/call", {"name": "stock_analysis", "arguments": {"ticker": "NVDA", "as_of": "June"}}))
    check("bad as_of -> -32602", r["error"]["code"] == -32602)
    r = m.handle(_rpc("tools/call", {"name": "place_order", "arguments": {}}))
    check("unknown tool -> -32602", r["error"]["code"] == -32602)
    r = m.handle(_rpc("tools/call", {"name": "compare_fundamentals", "arguments": {"tickers": ["A"] * 26}}))
    check("too many tickers -> -32602", r["error"]["code"] == -32602)

    seen = {}

    def fake_report(sym, **kw):
        seen.update(kw, sym=sym)
        return {"available": True, "symbol": sym, "score": {"score": 61.0}}
    with patch("stock_analysis.report.build_report", fake_report):
        r = m.handle(_rpc("tools/call", {"name": "stock_analysis",
                                         "arguments": {"ticker": "nvda", "as_of": "2025-06-30"}}))
    res = r["result"]
    check("report returned as text and structured content",
          json.loads(res["content"][0]["text"])["symbol"] == "NVDA" and res["structuredContent"]["score"]["score"] == 61)
    check("point-in-time date passed through", seen["as_of"] == "2025-06-30")
    check("never spends LLM credit (no MD&A summary)", seen["mdna_summary"] is False)
    check("default sections skip the raw statements", "statements" not in seen["include"])

    with patch("stock_analysis.report.build_report", lambda s, **k: {"available": False, "reason": "not an SEC filer"}):
        r = m.handle(_rpc("tools/call", {"name": "stock_analysis", "arguments": {"ticker": "SPY"}}))
    check("unavailable report -> isError result the model can read",
          r["result"]["isError"] and "not an SEC filer" in r["result"]["content"][0]["text"])

    def boom(sym, **k):
        raise RuntimeError("SEC unreachable")
    with patch("stock_analysis.report.build_report", boom):
        r = m.handle(_rpc("tools/call", {"name": "stock_analysis", "arguments": {"ticker": "AAPL"}}))
    check("tool exception -> isError result, not a crash",
          r["result"]["isError"] and "SEC unreachable" in r["result"]["content"][0]["text"])

    r = m.handle(_rpc("tools/call", {"name": "screener", "arguments": {}}))
    check("screener before its first build says so", r["result"]["isError"]
          and "not been built" in r["result"]["content"][0]["text"])
    r = m.handle(_rpc("tools/call", {"name": "filing_alerts", "arguments": {"limit": 5}}))
    check("alerts readable", r["result"]["structuredContent"]["alerts"] == [])


def test_transport():
    print("=== 3. HTTP transport ===")
    import web.app as app_mod
    c = app_mod.app.test_client()
    with patch.dict(os.environ, {"MCP_TOKEN": ""}):
        r = c.post("/mcp", json=_rpc("initialize", {"protocolVersion": "2025-06-18"}))
        check("initialize over HTTP", r.status_code == 200 and r.headers.get("MCP-Protocol-Version") == "2025-06-18")
        r = c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        check("notification -> 202, empty body", r.status_code == 202 and not r.data)
        r = c.post("/mcp", data="{not json", content_type="application/json")
        check("parse error -> -32700", r.status_code == 400 and r.get_json()["error"]["code"] == -32700)
        check("GET -> 405 (no event stream)", c.get("/mcp").status_code == 405)
        r = c.post("/mcp", json=_rpc("ping"), headers={"Origin": "https://evil.example"})
        check("cross-site browser origin refused", r.status_code == 403)
        r = c.post("/mcp", json=_rpc("ping"), headers={"Origin": "http://localhost"})
        check("same-origin allowed", r.status_code == 200)
    with patch.dict(os.environ, {"MCP_TOKEN": "s3cret"}):
        check("token set, none sent -> 401", c.post("/mcp", json=_rpc("ping")).status_code == 401)
        r = c.post("/mcp", json=_rpc("ping"), headers={"Authorization": "Bearer wrong"})
        check("wrong token -> 401", r.status_code == 401)
        r = c.post("/mcp", json=_rpc("ping"), headers={"Authorization": "Bearer s3cret"})
        check("right token -> 200", r.status_code == 200)


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
