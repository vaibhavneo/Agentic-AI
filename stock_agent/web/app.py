"""
Stock Agent Web Server — Flask port 5051
Powered by DeepSeek LLM (free, OpenAI-compatible)
"""
from __future__ import annotations

import json
import os
import sys
import queue
import threading
from pathlib import Path

# Load .env from project root
_root = Path(__file__).parent.parent
_env  = _root / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env)
    except ImportError:
        # Manual parse if dotenv not installed
        for line in _env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(_root))

from flask import Flask, Response, jsonify, request, stream_with_context
from agents.orchestrator import analyze_stock
from data.store import get_history, check_outcome, get_historical_hit_rate
from backtest.strategies import STRATEGY_REGISTRY

app = Flask(__name__, static_folder="static")


def _get_api_key() -> str:
    return (
        os.getenv("DEEPSEEK_API_KEY", "")
        or os.getenv("ANTHROPIC_API_KEY", "")
    )


@app.route("/")
def index():
    return (Path(__file__).parent / "static" / "index.html").read_text()


@app.route("/api/status")
def status():
    key = _get_api_key()
    return jsonify({
        "ok": bool(key),
        "key_set": bool(key),
        "key_preview": (key[:8] + "...") if key else None,
        "model": "deepseek-chat",
    })


@app.route("/api/analyze/stream", methods=["POST"])
def analyze_stream():
    data   = request.json or {}
    ticker = data.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "No ticker provided"}), 400

    api_key = _get_api_key()
    if not api_key:
        def err_gen():
            yield 'event: error\ndata: {"error": "No API key. Create .env file in stock_agent/ with: DEEPSEEK_API_KEY=sk-..."}\n\n'
            yield 'event: done\ndata: {}\n\n'
        return Response(stream_with_context(err_gen()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    result_queue: queue.Queue   = queue.Queue()
    progress_queue: queue.Queue = queue.Queue()

    def run():
        def on_progress(stage: str, msg: str):
            progress_queue.put(("progress", {"stage": stage, "msg": msg}))
        try:
            result = analyze_stock(ticker, api_key, verbose=False, on_progress=on_progress)
            result_queue.put(("result", result))
        except Exception as e:
            result_queue.put(("error", {"error": str(e)}))
        finally:
            result_queue.put(("done", {}))

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while True:
            try:
                while True:
                    evt, d = progress_queue.get_nowait()
                    yield f"event: {evt}\ndata: {json.dumps(d)}\n\n"
            except queue.Empty:
                pass
            try:
                evt, d = result_queue.get(timeout=0.2)
                if evt == "done":
                    try:
                        while True:
                            pe, pd = progress_queue.get_nowait()
                            yield f"event: {pe}\ndata: {json.dumps(pd)}\n\n"
                    except queue.Empty:
                        pass
                    yield "event: done\ndata: {}\n\n"
                    break
                else:
                    yield f"event: {evt}\ndata: {json.dumps(d, default=str)}\n\n"
            except queue.Empty:
                continue

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/quick", methods=["POST"])
def quick_data():
    ticker = (request.json or {}).get("ticker", "").upper()
    if not ticker:
        return jsonify({"error": "No ticker"}), 400
    try:
        from tools.market_data import (
            fetch_price_history, fetch_fundamentals, fetch_recent_news,
            compute_indicators, compute_signal_summary, compute_algo_signals,
        )
        df   = fetch_price_history(ticker, "3mo")
        fund = fetch_fundamentals(ticker)
        news = fetch_recent_news(ticker, 5)
        ind  = compute_indicators(df)
        sig  = compute_signal_summary(ind)
        algo = compute_algo_signals(df, ind)
        closes = df["Close"].tail(60).tolist()
        return jsonify({
            "ticker":         ticker,
            "company_name":   fund.get("longName", ticker),
            "sector":         fund.get("sector", ""),
            "current_price":  ind.get("current_price"),
            "change_pct":     ind.get("price_change_pct"),
            "indicators":     ind,
            "signal_summary": sig,
            "algo_signals":   algo,
            "news":           news,
            "sparkline":      [round(c, 2) for c in closes],
            "fundamentals": {
                "pe":             fund.get("trailingPE"),
                "forward_pe":     fund.get("forwardPE"),
                "market_cap":     fund.get("marketCap"),
                "target_price":   fund.get("targetMeanPrice"),
                "analyst_count":  fund.get("numberOfAnalystOpinions"),
                "52w_high":       fund.get("fiftyTwoWeekHigh"),
                "52w_low":        fund.get("fiftyTwoWeekLow"),
                "beta":           fund.get("beta"),
                "dividend":       fund.get("dividendYield"),
                "short_ratio":    fund.get("shortRatio"),
                "profit_margin":  fund.get("profitMargins"),
                "roe":            fund.get("returnOnEquity"),
                "revenue_growth": fund.get("revenueGrowth"),
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/strategies")
def list_strategies():
    return jsonify({"strategies": list(STRATEGY_REGISTRY.keys())})


@app.route("/api/backtest", methods=["POST"])
def run_backtest():
    data     = request.json or {}
    ticker   = data.get("ticker", "").upper()
    strategy = data.get("strategy", "sma_crossover")
    period   = data.get("period", "5y")
    if not ticker:
        return jsonify({"error": "No ticker"}), 400
    if strategy not in STRATEGY_REGISTRY:
        return jsonify({"error": f"Unknown strategy. Choose from: {list(STRATEGY_REGISTRY)}"}), 400
    try:
        import warnings; warnings.filterwarnings("ignore")
        from tools.market_data import fetch_price_history
        from backtest.engine import run_vectorized_backtest, compute_performance_metrics, deflated_sharpe_ratio
        from backtest.strategies import STRATEGIES_NEEDING_FULL_DF
        from backtest.risk import safe_kelly_fraction
        df     = fetch_price_history(ticker, period=period)
        prices = df["Close"]
        fn     = STRATEGY_REGISTRY[strategy]
        signal = fn(df) if strategy in STRATEGIES_NEEDING_FULL_DF else fn(prices)
        signal = signal.fillna(0)
        result = run_vectorized_backtest(prices, signal)
        m      = compute_performance_metrics(result.strategy_returns)
        dsr    = deflated_sharpe_ratio(
            m["sharpe_ratio"], n_trials=len(STRATEGY_REGISTRY),
            skewness=m["skewness"], kurtosis=m["kurtosis"], n_obs=m["n_observations"],
        )
        kelly = safe_kelly_fraction(result.strategy_returns)
        return jsonify({
            "ticker": ticker, "strategy": strategy, "period": period,
            "current_signal": int(signal.iloc[-1]),
            "sharpe":   round(m["sharpe_ratio"], 3),
            "sortino":  round(m["sortino_ratio"], 3),
            "max_dd":   round(m["max_drawdown"], 3),
            "calmar":   round(m["calmar_ratio"], 3),
            "win_rate": round(m["win_rate"], 3),
            "dsr":      round(dsr, 3),
            "n_trades": result.n_trades,
            "kelly_pct": round(kelly * 100, 1),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/track/history")
def track_history():
    ticker = request.args.get("ticker", "").upper() or None
    limit  = int(request.args.get("limit", 50))
    try:
        rows = get_history(ticker=ticker, limit=limit)
        return jsonify({"rows": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/track/check", methods=["POST"])
def track_check():
    data = request.json or {}
    rec_id = data.get("recommendation_id")
    if not rec_id:
        return jsonify({"error": "recommendation_id required"}), 400
    try:
        result = check_outcome(int(rec_id))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/track/hit_rate")
def track_hit_rate():
    strategy = request.args.get("strategy") or None
    ticker   = request.args.get("ticker", "").upper() or None
    try:
        result = get_historical_hit_rate(strategy_source=strategy, ticker=ticker)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5051))
    key  = _get_api_key()
    print(f"\n  Stock Agent AI  →  http://localhost:{port}")
    print(f"  Model: DeepSeek deepseek-chat (OpenAI-compatible)")
    print(f"  API Key: {'SET (' + key[:8] + '...)' if key else 'NOT SET — create stock_agent/.env with DEEPSEEK_API_KEY=sk-...'}")
    print(f"  Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
