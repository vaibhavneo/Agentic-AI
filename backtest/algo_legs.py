"""
The algo pillar, decomposed into the four signals it was always made of.

`compute_algo_signals` built one `algo_score` by voting, and the composite
weighted that score at 0.40 — the largest single weight in the system. Because
only the blend was ever recorded, nothing could ask which leg was carrying it.
Measuring them separately (49,880 daily observations, 20 large caps, 2016-2026)
answered two questions and the answers are why this module exists.

FIRST: the legs point OPPOSITE WAYS, year after year. Momentum and mean
reversion had opposite-signed 20-day IC in 7 of 11 calendar years — momentum
+0.164 in 2016 against mean reversion -0.106, momentum -0.098 in 2019 against
mean reversion +0.070. Voting them at EQUAL weight (2 and 2) is close to a
guarantee of cancellation, and the blend's measured IC of about +0.005 at 20
days is that cancellation.

SECOND, and the actual defect: the shipped score divides by the votes CAST,

    algo_score = bull / (bull + bear) * 100

so the denominator shrinks when fewer signals fire. One lonely bullish vote
scores 100 — maximum conviction — while three signals agreeing two-to-one score
67. Conviction therefore rises as evidence gets scarcer, which is backwards,
and it is not merely cosmetic:

    votes cast   n      mean |score-50|   IC 20d
    1            1214   50.0              -0.051
    2            2541   50.0              -0.066
    3            6430   39.8              +0.020
    4            2613   14.5              +0.040
    5            8966   14.8              +0.035

The two rows carrying MAXIMUM confidence are the two with NEGATIVE IC. 3,755
observations scored 0 or 100 on the strength of one or two votes, and those
scores were worse than useless.

`FIXED_DENOMINATOR` divides by the maximum vote weight instead, so the score
spans its range only when the legs actually agree. That is a correctness fix,
not an edge: measured out of sample it is still not positive. Which is the
honest headline of this whole decomposition — there is no durable signal in
these four legs to amplify. What the fix buys is a score that stops claiming
certainty from scarcity, and legs the self-improvement loop can down-weight on
their own measured record instead of one blended number nobody could attribute.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

# Leg names. These are the keys the loop tunes, so they are stated once.
MEAN_REVERSION = "mean_reversion"
MOMENTUM = "momentum"
TREND = "trend"
VOLUME = "volume"

LEGS = (MEAN_REVERSION, MOMENTUM, TREND, VOLUME)

# The shipped vote weights, kept as the DEFAULT so an untouched system scores
# exactly as it always did once the denominator question is settled.
DEFAULT_LEG_WEIGHTS: Dict[str, float] = {
    MEAN_REVERSION: 2.0, MOMENTUM: 2.0, TREND: 1.0, VOLUME: 2.0,
}

# Thresholds mirrored from tools/market_data.py's voting block and
# backtest/pillars.py::algo_score_series. Stated once here so the snapshot and
# the historical series cannot drift apart — they did not before, but they were
# two copies of the same numbers.
Z_BULL, Z_BEAR = -0.8, 0.8
MOM_BULL, MOM_BEAR = 3.0, -3.0
SLOPE_BULL, SLOPE_BEAR = 0.1, -0.1
VP_PRICE, VP_VOLUME = 0.02, 0.5

NEUTRAL = 50.0


def max_vote_weight(weights: Optional[Dict[str, float]] = None) -> float:
    """The denominator the FIXED scoring uses: total weight if every leg fired."""
    w = weights or DEFAULT_LEG_WEIGHTS
    return float(sum(abs(float(v)) for v in w.values())) or 1.0


def score_from_legs(votes: Dict[str, float],
                    weights: Optional[Dict[str, float]] = None,
                    fixed_denominator: bool = True) -> Dict[str, Any]:
    """Combine signed leg votes (-1 / 0 / +1) into a 0..100 score.

    `fixed_denominator=False` reproduces the shipped vote-ratio exactly, so the
    two can be measured against each other on identical inputs rather than
    compared across code paths.
    """
    w = dict(weights or DEFAULT_LEG_WEIGHTS)
    bull = bear = 0.0
    fired = 0
    for leg in LEGS:
        v = float(votes.get(leg) or 0.0)
        if v == 0.0:
            continue
        fired += 1
        if v > 0:
            bull += abs(w.get(leg, 0.0))
        else:
            bear += abs(w.get(leg, 0.0))

    cast = bull + bear
    if fixed_denominator:
        denom = max_vote_weight(w)
        score = NEUTRAL + (bull - bear) / denom * NEUTRAL
    else:
        score = (bull / cast * 100.0) if cast > 0 else NEUTRAL

    return {
        "score": round(max(0.0, min(100.0, score)), 4),
        "bull_weight": round(bull, 4),
        "bear_weight": round(bear, 4),
        "votes_cast_weight": round(cast, 4),
        "legs_fired": fired,
        "max_vote_weight": round(max_vote_weight(w), 4),
        "denominator": "fixed" if fixed_denominator else "votes_cast",
        # Breadth is reported because it is the thing the shipped denominator
        # destroyed: a reader can now tell one vote from four.
        "breadth": round(fired / len(LEGS), 4),
    }


def votes_from_signals(algo_signals: Dict[str, Any]) -> Dict[str, float]:
    """Signed leg votes from a live compute_algo_signals() result.

    Reads the SIGNAL strings the live scorer already produces rather than
    recomputing from prices, so the snapshot path cannot disagree with itself.
    """
    mr = str(algo_signals.get("mean_reversion_signal") or "").upper()
    mo = str(algo_signals.get("momentum_signal") or "").upper()
    tr = str(algo_signals.get("linreg_signal") or "").upper()
    vp = str(algo_signals.get("volume_price_signal") or "").upper()

    def _v(bull: bool, bear: bool) -> float:
        return 1.0 if bull else (-1.0 if bear else 0.0)

    return {
        MEAN_REVERSION: _v(mr in ("STRONG_BUY", "BUY"),
                           mr in ("STRONG_SELL", "SELL")),
        MOMENTUM: _v(mo in ("STRONG_BULLISH", "BULLISH"),
                     mo in ("STRONG_BEARISH", "BEARISH")),
        TREND: _v(tr in ("STRONG_UPTREND", "UPTREND"),
                  tr in ("STRONG_DOWNTREND", "DOWNTREND")),
        VOLUME: _v(vp == "CONFIRMED_BREAKOUT", vp == "CONFIRMED_BREAKDOWN"),
    }


def leg_series(df: pd.DataFrame) -> pd.DataFrame:
    """The four legs as signed vote series, bar by bar, with no look-ahead.

    Every input is backward-looking at each bar — a rolling mean, a shifted
    return, a rolling regression — so a value at index t was knowable at t.
    This is what makes a leg's record measurable over a decade instead of over
    the handful of snapshots the ledger happens to hold.
    """
    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float)

    z = ((close - close.rolling(20).mean())
         / close.rolling(20).std()).round(3).fillna(0.0)

    moms = [((close - close.shift(n)) / close.shift(n) * 100).round(2)
            for n in (21, 63, 126)]
    mom_df = pd.concat(moms, axis=1)
    mom = mom_df.mean(axis=1, skipna=True).round(2)
    mom_any = mom_df.notna().any(axis=1)

    win = 30
    x = np.arange(win, dtype=float)
    x_mean = x.mean()
    ss_xx = ((x - x_mean) ** 2).sum()

    def _slope_pct(w: np.ndarray) -> float:
        y_mean = w.mean()
        if y_mean == 0:
            return 0.0
        return round(((x - x_mean) * (w - y_mean)).sum() / ss_xx / y_mean * 100, 4)

    slope = close.rolling(win).apply(_slope_pct, raw=True)

    price_chg = (close - close.shift(5)) / close.shift(5)
    vol_ma = volume.rolling(20).mean()
    vol_chg = (volume - vol_ma) / vol_ma
    vp_ok = price_chg.notna() & vol_chg.notna() & (vol_ma > 0)

    out = pd.DataFrame(index=df.index)
    out[MEAN_REVERSION] = ((z < Z_BULL).astype(float)
                           - (z > Z_BEAR).astype(float))
    out[MOMENTUM] = ((mom_any & (mom > MOM_BULL)).astype(float)
                     - (mom_any & (mom < MOM_BEAR)).astype(float))
    out[TREND] = ((slope.notna() & (slope > SLOPE_BULL)).astype(float)
                  - (slope.notna() & (slope < SLOPE_BEAR)).astype(float))
    out[VOLUME] = ((vp_ok & (price_chg > VP_PRICE)
                    & (vol_chg > VP_VOLUME)).astype(float)
                   - (vp_ok & (price_chg < -VP_PRICE)
                      & (vol_chg > VP_VOLUME)).astype(float))
    return out


def score_series(df: pd.DataFrame, weights: Optional[Dict[str, float]] = None,
                 fixed_denominator: bool = True) -> pd.Series:
    """The combined algo score, bar by bar, under a given weighting."""
    legs = leg_series(df)
    w = dict(weights or DEFAULT_LEG_WEIGHTS)
    bull = pd.Series(0.0, index=df.index)
    bear = pd.Series(0.0, index=df.index)
    for leg in LEGS:
        wt = abs(float(w.get(leg, 0.0)))
        bull += legs[leg].clip(lower=0) * wt
        bear += (-legs[leg]).clip(lower=0) * wt

    if fixed_denominator:
        score = NEUTRAL + (bull - bear) / max_vote_weight(w) * NEUTRAL
    else:
        cast = bull + bear
        score = (bull / cast.replace(0, np.nan) * 100.0).fillna(NEUTRAL)
    return score.clip(0.0, 100.0)


# ── scorer identity ───────────────────────────────────────────────────────
#
# strategy_version in the ledger is experiments.manifest_hash(), which
# fingerprints the pre-registered VARIANT REGISTRY — not the scorer. So
# changing how algo_score is computed does not move it, and old and new rows
# would be indistinguishable in the ledger while calibration silently averaged
# two different scorers together. That is the exact silent-failure shape this
# codebase keeps encoding lessons about, so the scorer gets its own identity.
#
# Attribution and calibration can then filter to one scorer, or state plainly
# that a population spans two.

SCORER_NAME = "algo_legs"


def scorer_version(weights: Optional[Dict[str, float]] = None,
                   fixed_denominator: bool = True) -> str:
    """Fingerprint of everything that determines an algo score."""
    import hashlib
    import json as _json
    w = dict(weights or DEFAULT_LEG_WEIGHTS)
    blob = _json.dumps({
        "scorer": SCORER_NAME,
        "weights": {k: round(float(w.get(k, 0.0)), 6) for k in LEGS},
        "denominator": "fixed" if fixed_denominator else "votes_cast",
        "thresholds": {"z": [Z_BULL, Z_BEAR], "mom": [MOM_BULL, MOM_BEAR],
                       "slope": [SLOPE_BULL, SLOPE_BEAR],
                       "vp": [VP_PRICE, VP_VOLUME]},
    }, sort_keys=True)
    return f"{SCORER_NAME}:{hashlib.sha1(blob.encode()).hexdigest()[:12]}"


# The version every row scored before the decomposition landed. Rows in the
# ledger with no scorer_version at all predate this and are that version by
# definition; naming it lets a query say so instead of treating NULL as unknown.
LEGACY_SCORER_VERSION = "algo_votes_cast:pre-2026-09-26"
