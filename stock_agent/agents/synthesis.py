"""
Phase 5 — Grounded Synthesis
============================
Replaces the LLM-invented entry/target/stop numbers with values computed
from backtested strategies.  The LLM prose (summary, bull_case, bear_case)
is left completely untouched; only the numeric fields are overwritten.

Flow:
  1. Run all 7 strategies against already-fetched price history.
  2. Find the strategy whose current signal agrees with the LLM's action.
  3. If found:
       entry_price  = current_price  (deterministic)
       stop_loss    = current_price - 1.5 * ATR_14   (risk anchor)
       target_price = entry + 2 * (entry - stop_loss)  (2:1 R:R)
       position_size = safe_kelly_fraction(strategy_returns)
       confidence    = get_historical_hit_rate(strategy)
  4. If no strategy agrees: downgrade conviction to LOW, flag grounding="none".
  5. Return original pred dict extended with grounding_* fields.
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from backtest.engine import run_vectorized_backtest, compute_performance_metrics, deflated_sharpe_ratio
from backtest.strategies import STRATEGY_REGISTRY, STRATEGIES_NEEDING_FULL_DF
from backtest.risk import safe_kelly_fraction
from data.store import get_historical_hit_rate


_LONG_ACTIONS  = {"BUY", "LONG", "STRONG BUY"}
_SHORT_ACTIONS = {"SELL", "SHORT", "AVOID", "STRONG SELL"}
_N_TRIALS      = len(STRATEGY_REGISTRY)


def ground_prediction(
    ticker: str,
    current_price: float,
    llm_prediction: dict,
    price_df: pd.DataFrame,
    indicators: dict,
) -> dict:
    """
    Core grounding function.

    Parameters
    ----------
    ticker         : e.g. "AAPL"
    current_price  : latest closing price
    llm_prediction : the dict returned by run_prediction_agent()
    price_df       : full OHLCV DataFrame (from fetch_price_history)
    indicators     : dict from compute_indicators()

    Returns
    -------
    A copy of llm_prediction with numeric fields overwritten (or downgraded)
    and new grounding_* fields appended.
    """
    pred   = dict(llm_prediction)
    prices = price_df["Close"].dropna()

    raw_action = str(pred.get("action") or pred.get("recommendation") or "").upper().strip()

    if raw_action in _LONG_ACTIONS:
        wanted_signal = 1
    elif raw_action in _SHORT_ACTIONS:
        wanted_signal = -1
    else:
        wanted_signal = 0

    # ── Run all strategies, collect their current signal + returns ─────────
    strategy_results: list[dict] = []
    for name, fn in STRATEGY_REGISTRY.items():
        try:
            signal = fn(price_df) if name in STRATEGIES_NEEDING_FULL_DF else fn(prices)
            signal = signal.fillna(0)
            if len(signal) == 0:
                continue
            result  = run_vectorized_backtest(prices, signal)
            metrics = compute_performance_metrics(result.strategy_returns)
            dsr     = deflated_sharpe_ratio(
                metrics["sharpe_ratio"],
                n_trials=_N_TRIALS,
                skewness=metrics["skewness"],
                kurtosis=metrics["kurtosis"],
                n_obs=metrics["n_observations"],
            )
            current_sig = int(signal.iloc[-1])
            strategy_results.append({
                "name":    name,
                "signal":  current_sig,
                "sharpe":  metrics["sharpe_ratio"],
                "dsr":     dsr,
                "returns": result.strategy_returns,
                "kelly":   safe_kelly_fraction(result.strategy_returns),
            })
        except Exception:
            continue

    # ── Find best agreeing strategy ────────────────────────────────────────
    # A strategy only counts as genuine support if it (a) currently points the
    # same direction as the LLM AND (b) has a POSITIVE historical edge. A
    # losing strategy (Sharpe <= 0) that happens to point the same way is not
    # evidence for the call — treating it as grounding would let a money-losing
    # rule "confirm" a BUY and keep conviction HIGH, which defeats the purpose.
    directional = [s for s in strategy_results if s["signal"] == wanted_signal and wanted_signal != 0]
    agreeing    = [s for s in directional if s["sharpe"] > 0]
    # rank by dSR then Sharpe
    agreeing.sort(key=lambda s: (s["dsr"], s["sharpe"]), reverse=True)

    best = agreeing[0] if agreeing else None
    # how many pointed the right way but had no edge (for an honest note)
    n_directional_no_edge = len(directional) - len(agreeing)

    # ── Compute ATR for stop distance ──────────────────────────────────────
    atr = _compute_atr(price_df, window=14)

    # ── Build grounded numbers ─────────────────────────────────────────────
    if best is not None:
        stop_distance  = max(1.5 * atr, current_price * 0.01)  # at least 1%
        entry_price    = round(current_price, 2)

        if wanted_signal >= 0:   # long or neutral
            stop_loss    = round(current_price - stop_distance, 2)
            target_price = round(current_price + 2 * stop_distance, 2)
        else:                    # short
            stop_loss    = round(current_price + stop_distance, 2)
            target_price = round(current_price - 2 * stop_distance, 2)

        upside_pct    = round((target_price - current_price) / current_price * 100, 1)
        position_size = best["kelly"]

        hist_hit = get_historical_hit_rate(strategy_source=best["name"], ticker=ticker)

        pred["entry_price"]  = entry_price
        pred["target_price"] = target_price
        pred["stop_loss"]    = stop_loss
        pred["upside_pct"]   = upside_pct

        grounding = {
            "grounding":                  "strategy",
            "grounding_strategy":         best["name"],
            "grounding_backtest_sharpe":  round(best["sharpe"], 3),
            "grounding_dsr":              round(best["dsr"], 3),
            "grounding_historical_hit_rate": hist_hit.get("hit_rate"),
            "grounding_hit_rate_n":       hist_hit.get("total", 0),
            "grounding_atr":              round(atr, 3),
            "position_size":              position_size,
            "n_agreeing_strategies":      len(agreeing),
            "all_strategy_signals":       {s["name"]: s["signal"] for s in strategy_results},
        }
    else:
        # No strategy agrees — downgrade conviction, flag clearly
        grounding = {
            "grounding":                  "none",
            "grounding_strategy":         None,
            "grounding_backtest_sharpe":  None,
            "grounding_dsr":              None,
            "grounding_historical_hit_rate": None,
            "grounding_hit_rate_n":       0,
            "grounding_atr":              round(atr, 3),
            "position_size":              0.0,
            "n_agreeing_strategies":      0,
            "n_directional_no_edge":      n_directional_no_edge,
            "all_strategy_signals":       {s["name"]: s["signal"] for s in strategy_results},
        }
        pred["conviction"] = "LOW"

    pred.update(grounding)
    return pred


# ── Helpers ────────────────────────────────────────────────────────────────

def _compute_atr(df: pd.DataFrame, window: int = 14) -> float:
    """Average True Range over the last `window` bars."""
    try:
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(window).mean().iloc[-1])
        return atr if (atr > 0 and not np.isnan(atr)) else close.iloc[-1] * 0.02
    except Exception:
        return float(df["Close"].iloc[-1]) * 0.02
