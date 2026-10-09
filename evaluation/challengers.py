"""
Challengers — simple models scored on the SAME calls as the desk's composite.

The question a scorecard alone cannot answer: is the 7-pillar engine better
than a one-line screen? A composite with rank IC +0.08 is only worth its
complexity if 12-1 momentum, on the same names and days, does worse.

Two kinds:

  PILLAR  derived from the frozen pillars (fundamentals only, technical only,
          equal-weight core). Computed on the fly — the inputs are immutable.
  PRICE   computed from the price series UP TO AND INCLUDING the call date
          (12-1 momentum, 1-month reversal, low volatility). That is exactly
          what the desk knew when it made the call, so reconstructing them for
          past calls is point-in-time valid; new calls get theirs frozen at the
          moment of the call (source = 'frozen'). Stored in `shadow_scores`.

A challenger that beats the composite is the most useful thing this module can
report, and it never changes a score. Promotion is a decision for a person, made
on the paired verdict in evaluation/scorecard.challenger_scorecard.

Adding a new data source? Add it here as a challenger, let it accumulate a
record beside the composite, and wire it into the decision only if it wins.
The event signals in backtest/event_signals_eval.py are the cautionary tale:
they failed their pre-stated rule and were never wired in.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

# ── Challenger definitions ────────────────────────────────────────────────

def _ret(close, back: int, skip: int = 0) -> Optional[float]:
    """Return from `back` bars ago to `skip` bars ago (0 = the last bar)."""
    if close is None or len(close) <= back:
        return None
    a, b = float(close.iloc[-1 - back]), float(close.iloc[-1 - skip])
    return None if a <= 0 else b / a - 1.0


def _momentum_12_1(close) -> Optional[float]:
    # The textbook momentum factor: last 12 months excluding the most recent one.
    return _ret(close, 252, 21)


def _reversal_1m(close) -> Optional[float]:
    r = _ret(close, 21)
    return None if r is None else -r


def _low_volatility(close) -> Optional[float]:
    if close is None or len(close) < 61:
        return None
    px = [float(x) for x in close.iloc[-61:]]
    rets = [px[i] / px[i - 1] - 1.0 for i in range(1, len(px)) if px[i - 1] > 0]
    if len(rets) < 40:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
    return -sd


PRICE_CHALLENGERS: Dict[str, Callable] = {
    "momentum_12_1": _momentum_12_1,
    "reversal_1m": _reversal_1m,
    "low_volatility": _low_volatility,
}


def _pillar(name):
    return lambda pillars, composite, rec: pillars.get(name)


def _equal_core(pillars, composite, rec):
    vals = [pillars.get(k) for k in ("technical", "algo", "fundamentals")]
    return None if any(v is None for v in vals) else sum(vals) / 3.0


def _pre_risk(rec) -> Optional[float]:
    """clip(core + modifiers): the composite BEFORE the risk step, rebuilt
    exactly from what the call froze (backtest/pillars.py's formula)."""
    core = (rec or {}).get("core_score")
    if core is None:
        return None
    return max(0.0, min(100.0, float(core) + float((rec or {}).get("modifier_pts") or 0.0)))


def _no_risk(pillars, composite, rec):
    # The 2017-2025 replay found the risk pillar ranking BACKWARDS (IC -0.066,
    # t=-4.04 at 126d). These two test what the composite would have done
    # without its risk multiplier/veto, and with the multiplier inverted.
    return _pre_risk(rec)


def _risk_inverted(pillars, composite, rec):
    pre, risk = _pre_risk(rec), pillars.get("risk")
    if pre is None or risk is None:
        return None
    return 50.0 + (pre - 50.0) * (0.5 + 0.5 * (100.0 - float(risk)) / 100.0)


PILLAR_CHALLENGERS: Dict[str, Callable] = {
    "fundamentals_only": _pillar("fundamentals"),
    "technical_only": _pillar("technical"),
    "equal_weight_core": _equal_core,
    "composite_no_risk": _no_risk,
    "composite_risk_inverted": _risk_inverted,
}

CHALLENGERS = tuple(PRICE_CHALLENGERS) + tuple(PILLAR_CHALLENGERS)

DESCRIPTIONS = {
    "momentum_12_1": "12-month return excluding the last month (classic momentum)",
    "reversal_1m": "minus the last month's return (short-term reversal)",
    "low_volatility": "minus 60-day volatility (calmer names rank higher)",
    "fundamentals_only": "the fundamentals pillar alone",
    "technical_only": "the technical pillar alone",
    "equal_weight_core": "technical, algo and fundamentals at equal weight",
    "composite_no_risk": "the desk's composite without the risk multiplier and veto",
    "composite_risk_inverted": "the desk's composite with the risk multiplier inverted (riskier names amplified)",
}


def price_scores(close) -> Dict[str, float]:
    """All price challengers from a close series that ends AT the call."""
    out = {}
    for name, fn in PRICE_CHALLENGERS.items():
        try:
            v = fn(close)
        except Exception:
            v = None
        if v is not None and math.isfinite(v):
            out[name] = round(float(v), 6)
    return out


def pillar_scores(pillars: Dict[str, Any], composite: Optional[float],
                  rec: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    out = {}
    for name, fn in PILLAR_CHALLENGERS.items():
        v = fn(pillars or {}, composite, rec or {})
        if v is not None:
            out[name] = float(v)
    return out


# ── Storage ───────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_scores (
    snapshot_id  TEXT NOT NULL,
    challenger   TEXT NOT NULL,
    value        REAL NOT NULL,
    source       TEXT NOT NULL,          -- 'frozen' at the call, or 'reconstructed'
    computed_at  TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, challenger)
);
-- A score frozen at the call is evidence, like the call itself: never edited.
CREATE TRIGGER IF NOT EXISTS shadow_scores_frozen_no_update
BEFORE UPDATE ON shadow_scores WHEN OLD.source = 'frozen'
BEGIN SELECT RAISE(ABORT, 'frozen shadow scores are immutable'); END;
CREATE TRIGGER IF NOT EXISTS shadow_scores_frozen_no_delete
BEFORE DELETE ON shadow_scores WHEN OLD.source = 'frozen'
BEGIN SELECT RAISE(ABORT, 'frozen shadow scores are immutable'); END;
"""


def _conn() -> sqlite3.Connection:
    from data import prediction_ledger as pl
    conn = sqlite3.connect(pl._db(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _write(snapshot_id: str, scores: Dict[str, float], source: str) -> int:
    if not snapshot_id or not scores:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        frozen = {r["challenger"] for r in conn.execute(
            "SELECT challenger FROM shadow_scores WHERE snapshot_id=? AND source='frozen'", (snapshot_id,))}
        n = 0
        for name, v in scores.items():
            if name in frozen:
                continue                     # a frozen value is never replaced
            conn.execute("DELETE FROM shadow_scores WHERE snapshot_id=? AND challenger=?",
                         (snapshot_id, name))
            conn.execute("INSERT INTO shadow_scores VALUES (?,?,?,?,?)",
                         (snapshot_id, name, float(v), source, now))
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def record_frozen(snapshot_id: str, close) -> int:
    """At the call: freeze every price challenger beside the desk's call."""
    try:
        return _write(snapshot_id, price_scores(close), "frozen")
    except Exception:
        return 0


def load(snapshot_ids: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, float]]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT snapshot_id, challenger, value FROM shadow_scores").fetchall()
    finally:
        conn.close()
    wanted = set(snapshot_ids) if snapshot_ids is not None else None
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        if wanted is None or r["snapshot_id"] in wanted:
            out.setdefault(r["snapshot_id"], {})[r["challenger"]] = r["value"]
    return out


MAX_STALE_DAYS = 7


def reconstruct(fetch_fn: Optional[Callable[[str, str], Any]] = None) -> Dict[str, Any]:
    """Fill price challengers for calls that have none, from prices up to each
    call date. Point-in-time: the series is cut at the call date, and a call
    whose last available bar is more than a week before it is skipped."""
    import pandas as pd
    from data import prediction_ledger as pl

    conn = _conn()
    try:
        todo = [dict(r) for r in conn.execute(
            """SELECT s.snapshot_id, s.ticker, substr(s.created_at,1,10) AS day
                 FROM prediction_snapshots s
                WHERE s.snapshot_id NOT IN (SELECT snapshot_id FROM shadow_scores)""").fetchall()]
    finally:
        conn.close()
    if fetch_fn is None:
        def fetch_fn(t, period):
            from tools.market_data import fetch_price_history
            return fetch_price_history(t, period=period)["Close"]

    by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for s in todo:
        by_ticker.setdefault(s["ticker"], []).append(s)
    written, skipped, errors = 0, 0, []
    for tkr, snaps in by_ticker.items():
        oldest = min(s["day"] for s in snaps)
        # One extra year of history before the oldest call for the 12-month lookback.
        period = pl.history_period(
            (pd.Timestamp(oldest) - pd.Timedelta(days=380)).strftime("%Y-%m-%d"))
        try:
            close = fetch_fn(tkr, period).dropna()
        except Exception as e:
            errors.append(f"{tkr}: {str(e)[:60]}")
            continue
        for s in snaps:
            # Compare CALENDAR DATES: vendor bars are stamped 04:00, so
            # "<= midnight of the call day" silently dropped the call day's own
            # close — the one the desk priced the call at.
            day = pd.Timestamp(s["day"])
            cut = close[close.index < day + pd.Timedelta(days=1)]
            if not len(cut) or (day - cut.index[-1].normalize()).days > MAX_STALE_DAYS:
                skipped += 1
                continue
            written += _write(s["snapshot_id"], price_scores(cut), "reconstructed")
    return {"snapshots_considered": len(todo), "scores_written": written,
            "skipped_no_history": skipped, "errors": errors}
