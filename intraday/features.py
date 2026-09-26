"""
Intraday features, measured in BARS rather than days.

Everything else in this system reasons in trading days, and that choice is what
made the long horizons unverifiable: twenty independent one-year windows need
twenty years of history, so the 252-day record rests on three. Intraday inverts
that arithmetic completely. A month of five-minute bars is 1,716 observations,
and at a four-bar horizon it contains roughly 429 NON-OVERLAPPING windows — more
independent evidence than the daily ledger has accumulated at any horizon in four
years.

That is the honest argument for looking here: not that intraday edge is likely,
but that intraday is the one place where a measurement can actually settle the
question instead of gesturing at three windows.

The argument against is costs, and it is severe. At 20 days the cross-sectional
study lost 64% of a +0.313% gross signal to 20bps of round-trip cost. Intraday
gross moves are an order of magnitude smaller while the spread is unchanged, so
a strategy that ignores it is fiction. `net_of_costs` is therefore not optional
here and the evaluation reports gross and net side by side.

Data limits are real and stated rather than discovered: the vendor keeps roughly
30 days of 1-minute bars and 60 days of 5- to 30-minute bars, so the whole
intraday sample sits inside one or two months — one market regime. Abundant
independent windows WITHIN a regime is not the same as evidence across regimes,
and nothing here should be read as the latter.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# Feature names, stated once so the evaluator and any consumer agree.
RET_1 = "ret_1bar"
RET_4 = "ret_4bar"
RET_12 = "ret_12bar"
ZSCORE = "zscore_20bar"
RANGE_POS = "range_position"
VOL_RATIO = "volume_ratio"
REALIZED_VOL = "realized_vol_20bar"
GAP_FROM_OPEN = "gap_from_open"
MINUTES_IN = "minutes_since_open"

FEATURES = (RET_1, RET_4, RET_12, ZSCORE, RANGE_POS, VOL_RATIO,
            REALIZED_VOL, GAP_FROM_OPEN)

# Bars per session, by interval. Used to derive session-relative features and to
# state a horizon in something a reader can picture.
BARS_PER_SESSION = {"1m": 390, "2m": 195, "5m": 78, "15m": 26, "30m": 13,
                    "60m": 7, "1h": 7}


def bars_to_minutes(bars: int, interval: str) -> int:
    per = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60}
    return int(bars) * per.get(interval, 5)


def load(symbol: str, interval: str = "5m", period: str = "1mo"
         ) -> Optional[pd.DataFrame]:
    """Intraday bars through the gateway, as a frame indexed by bar timestamp."""
    from financial_data.gateway import get

    r = get("intraday", symbol, period=period, interval=interval)
    rows = []
    for d in (r.get("data") or []):
        ex = d.get("extra") or {}
        rows.append({"ts": d.get("available_at"), "close": float(d["value"]),
                     "open": float(ex.get("open") or d["value"]),
                     "high": float(ex.get("high") or d["value"]),
                     "low": float(ex.get("low") or d["value"]),
                     "volume": float(ex.get("volume") or 0.0)})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"]).set_index("ts").sort_index()
    return df if len(df) else None


def compute(df: pd.DataFrame, interval: str = "5m") -> pd.DataFrame:
    """Backward-looking intraday features. No value uses a later bar.

    Session boundaries matter more here than at daily frequency: a return
    computed ACROSS an overnight gap is a different quantity from one computed
    within a session, and averaging the two produces a feature that measures
    partly the gap and partly the drift. Session-relative features are therefore
    reset each day rather than rolled continuously.
    """
    out = pd.DataFrame(index=df.index)
    close = df["close"].astype(float)
    session = df.index.tz_convert("America/New_York").date

    out[RET_1] = close.pct_change(1) * 100.0
    out[RET_4] = close.pct_change(4) * 100.0
    out[RET_12] = close.pct_change(12) * 100.0

    roll_mean = close.rolling(20).mean()
    roll_std = close.rolling(20).std()
    out[ZSCORE] = ((close - roll_mean) / roll_std).replace(
        [np.inf, -np.inf], np.nan)

    hi = df["high"].rolling(20).max()
    lo = df["low"].rolling(20).min()
    span = (hi - lo).replace(0, np.nan)
    out[RANGE_POS] = ((close - lo) / span) * 2.0 - 1.0     # -1 .. +1

    vol = df["volume"].astype(float)
    vol_ma = vol.rolling(20).mean().replace(0, np.nan)
    out[VOL_RATIO] = (vol / vol_ma) - 1.0

    rets = close.pct_change()
    bars_yr = BARS_PER_SESSION.get(interval, 78) * 252
    out[REALIZED_VOL] = rets.rolling(20).std() * math.sqrt(bars_yr) * 100.0

    # Distance from THIS session's open, reset daily. Rolled continuously it
    # would silently measure the overnight gap as well.
    ses = pd.Series(session, index=df.index)
    first_open = df.groupby(ses)["open"].transform("first")
    out[GAP_FROM_OPEN] = (close / first_open - 1.0) * 100.0

    out[MINUTES_IN] = (pd.Series(
        df.index.tz_convert("America/New_York"), index=df.index)
        .groupby(ses).transform(lambda s: (s - s.iloc[0]).dt.total_seconds() / 60.0))

    out["_session"] = ses
    return out


def forward_return(df: pd.DataFrame, bars: int,
                   same_session_only: bool = True) -> pd.Series:
    """Return over the next `bars` bars, in percent.

    `same_session_only` drops any window that would cross an overnight gap. The
    gap is not something an intraday signal forecasts, and leaving it in makes
    the overnight move the dominant term in a short-horizon measurement — which
    reads as edge and is not.
    """
    close = df["close"].astype(float)
    fwd = (close.shift(-bars) / close - 1.0) * 100.0
    if not same_session_only:
        return fwd
    session = pd.Series(df.index.tz_convert("America/New_York").date,
                        index=df.index)
    same = session.shift(-bars) == session
    return fwd.where(same)
