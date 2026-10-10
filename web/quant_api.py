"""Quant Lab endpoints (a Flask blueprint registered by web/app.py).

    GET  /quant                  the ⚡ Quant Lab page
    POST /api/quant/risk         {holdings, years?}
    POST /api/quant/optimize     {symbols | holdings, method: min_variance|max_sharpe|risk_parity|all,
                                  max_weight?, years?, cash?} — with holdings, the rebalance trades too
    POST /api/quant/project      {holdings, years?, monthly_contribution?, goal?, drift?, expected_return?}
    GET  /api/quant/scan         ?symbols=A,B — today's intraday signals, each with its rule's record
    GET  /api/quant/backtest     ?symbols=A,B — every rule replayed on ~60 sessions of 5-minute bars
    GET  /api/quant/journal      the paper journal: recent signals, outcomes, per-rule stats

The live signal board streams from /api/live/stream?kinds=signal,signal_close
(when LIVE_FEEDS=1). Holdings are {symbol, shares} or {symbol, value}.
Everything is research; nothing here places an order.
"""
from __future__ import annotations

import re
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

bp = Blueprint("quant", __name__)
SYM = re.compile(r"^[A-Z0-9.\-^=]{1,10}$")
METHODS = ("min_variance", "max_sharpe", "risk_parity")


class BadRequest(ValueError):
    pass


def _symbols(raw) -> list:
    if isinstance(raw, str):
        raw = raw.split(",")
    syms = [str(s).strip().upper() for s in (raw or []) if str(s).strip()]
    bad = [s for s in syms if not SYM.match(s)]
    if bad:
        raise BadRequest(f"not a symbol: {bad[0]}")
    if len(syms) > 40:
        raise BadRequest("40 symbols at most")
    return list(dict.fromkeys(syms))


def _holdings(raw) -> list:
    if not isinstance(raw, list) or not raw:
        raise BadRequest("holdings must be a non-empty list of {symbol, shares} or {symbol, value}")
    out = []
    for h in raw[:40]:
        if not isinstance(h, dict):
            raise BadRequest("each holding is {symbol, shares} or {symbol, value}")
        sym = _symbols([h.get("symbol") or h.get("ticker") or ""])
        if not sym:
            raise BadRequest("a holding has no symbol")
        try:
            if h.get("value") is not None:
                v = float(h["value"])
                item = {"symbol": sym[0], "value": v}
            else:
                v = float(h.get("shares"))
                item = {"symbol": sym[0], "shares": v}
        except (TypeError, ValueError):
            raise BadRequest(f"{sym[0]}: shares or value must be a number")
        if v <= 0:
            raise BadRequest(f"{sym[0]}: shares or value must be positive")
        out.append(item)
    return out


def _num(data, key, default, lo, hi, cast=float):
    try:
        v = cast(data.get(key, default) if data.get(key) is not None else default)
    except (TypeError, ValueError):
        raise BadRequest(f"{key} must be a number")
    if not lo <= v <= hi:
        raise BadRequest(f"{key} must be between {lo} and {hi}")
    return v


def _run(fn):
    try:
        return jsonify(fn())
    except BadRequest as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:                        # not enough history, unknown method, …
        return jsonify({"error": str(e)}), 422
    except Exception as e:                         # price source down
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502


@bp.route("/quant")
def quant_page():
    return Response((Path(__file__).parent / "static" / "quant.html").read_text(), mimetype="text/html")


@bp.route("/api/quant/risk", methods=["POST"])
def quant_risk():
    from quant import portfolio as Q
    data = request.json or {}
    return _run(lambda: Q.risk(_holdings(data.get("holdings")), years=_num(data, "years", 3, 1, 5, int)))


@bp.route("/api/quant/optimize", methods=["POST"])
def quant_optimize():
    from quant import portfolio as Q
    data = request.json or {}

    def go():
        holdings = _holdings(data["holdings"]) if data.get("holdings") else None
        syms = _symbols(data.get("symbols")) or [h["symbol"] for h in holdings or []]
        if len(syms) < 2:
            raise BadRequest("give at least two symbols (or holdings)")
        method = data.get("method") or "max_sharpe"
        if method not in METHODS + ("all",):
            raise BadRequest("method must be min_variance, max_sharpe, risk_parity or all")
        kw = {"max_weight": _num(data, "max_weight", 0.35, 0.05, 1.0), "years": _num(data, "years", 3, 1, 5, int)}
        results = {m: Q.optimize(syms, m, **kw) for m in (METHODS if method == "all" else (method,))}
        if holdings:
            cash = _num(data, "cash", 0, 0, 1e9)
            for r in results.values():
                r["rebalance"] = Q.rebalance(holdings, r["weights"], cash=cash)
        return results if method == "all" else results[method]
    return _run(go)


@bp.route("/api/quant/project", methods=["POST"])
def quant_project():
    from quant import portfolio as Q
    data = request.json or {}

    def go():
        drift = data.get("drift") or "conservative"
        if drift not in ("conservative", "historical"):
            raise BadRequest("drift must be conservative or historical")
        goal = data.get("goal")
        return Q.project(_holdings(data.get("holdings")), years=_num(data, "years", 10, 1, 40, int),
                         monthly_contribution=_num(data, "monthly_contribution", 0, 0, 1e7),
                         goal=_num(data, "goal", 0, 0, 1e12) if goal not in (None, "", 0) else None,
                         drift=drift, expected_return=_num(data, "expected_return", 0.07, -0.2, 0.3))
    return _run(go)


@bp.route("/api/quant/scan")
def quant_scan():
    from quant import live as QL
    return _run(lambda: QL.scan_all(_symbols(request.args.get("symbols")) or None))


@bp.route("/api/quant/backtest")
def quant_backtest():
    from quant import live as QL
    return _run(lambda: QL.backtest_today(_symbols(request.args.get("symbols")) or None))


@bp.route("/api/quant/journal")
def quant_journal():
    from quant import live as QL
    return _run(lambda: QL.journal_summary(int(request.args.get("limit") or 30)))
