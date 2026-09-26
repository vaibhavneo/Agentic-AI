"""
The algo pillar's four legs.

The defect this module exists to fix was measurable, so the tests assert the
measured properties rather than just that the arithmetic runs: conviction must
rise with AGREEMENT, not fall with evidence, and the historical series must
score identically to the live scorer or the backtest measures a strategy nobody
is running.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import algo_legs as AL


def _votes(**kw):
    v = {leg: 0.0 for leg in AL.LEGS}
    v.update(kw)
    return v


# ── the defect ────────────────────────────────────────────────────────────

def test_one_vote_no_longer_scores_maximum_conviction():
    """The shipped score divided by the votes CAST, so a single bullish vote
    scored 100. Measured over 49,880 observations the one- and two-vote buckets
    carried maximum confidence and NEGATIVE 20-day IC (-0.051, -0.066)."""
    one = AL.score_from_legs(_votes(momentum=1.0))
    assert one["score"] < 100.0
    assert one["legs_fired"] == 1
    # And the old behaviour is still reachable, for comparison, not for use.
    assert AL.score_from_legs(_votes(momentum=1.0),
                              fixed_denominator=False)["score"] == 100.0


def test_conviction_rises_with_agreement():
    """The property the vote-ratio inverted: more legs agreeing must read as
    more conviction, not less."""
    scores = [
        AL.score_from_legs(_votes(momentum=1.0))["score"],
        AL.score_from_legs(_votes(momentum=1.0, mean_reversion=1.0))["score"],
        AL.score_from_legs(_votes(momentum=1.0, mean_reversion=1.0,
                                  trend=1.0))["score"],
        AL.score_from_legs(_votes(momentum=1.0, mean_reversion=1.0,
                                  trend=1.0, volume=1.0))["score"],
    ]
    assert scores == sorted(scores), f"conviction did not rise: {scores}"
    assert scores[-1] == 100.0, "unanimous agreement should reach the ceiling"


def test_the_old_denominator_was_flat_across_breadth():
    """Why the fix was needed at all: one, two, three and four agreeing votes
    all scored exactly the same under the vote-ratio."""
    old = [AL.score_from_legs(v, fixed_denominator=False)["score"] for v in (
        _votes(momentum=1.0),
        _votes(momentum=1.0, mean_reversion=1.0),
        _votes(momentum=1.0, mean_reversion=1.0, trend=1.0),
        _votes(momentum=1.0, mean_reversion=1.0, trend=1.0, volume=1.0))]
    assert old == [100.0, 100.0, 100.0, 100.0]


def test_opposing_legs_read_neutral():
    """Momentum and mean reversion had opposite-signed IC in 7 of 11 years.
    When they disagree the honest score is neutral, not a coin-flip extreme."""
    s = AL.score_from_legs(_votes(momentum=1.0, mean_reversion=-1.0))
    assert s["score"] == pytest.approx(AL.NEUTRAL)


def test_no_votes_is_neutral_not_zero():
    s = AL.score_from_legs(_votes())
    assert s["score"] == pytest.approx(AL.NEUTRAL)
    assert s["legs_fired"] == 0
    assert s["breadth"] == 0.0


def test_the_score_stays_in_range_under_any_weighting():
    heavy = {leg: AL.DEFAULT_LEG_WEIGHTS[leg] * 10 for leg in AL.LEGS}
    for v in (_votes(momentum=1.0), _votes(momentum=-1.0),
              _votes(**{leg: 1.0 for leg in AL.LEGS})):
        s = AL.score_from_legs(v, heavy)
        assert 0.0 <= s["score"] <= 100.0


def test_breadth_is_reported_so_one_vote_is_distinguishable_from_four():
    """The vote-ratio destroyed this distinction; it is the thing a reader
    needs to judge a score by."""
    assert AL.score_from_legs(_votes(momentum=1.0))["breadth"] == 0.25
    assert AL.score_from_legs(
        _votes(**{leg: 1.0 for leg in AL.LEGS}))["breadth"] == 1.0


# ── leg weighting ─────────────────────────────────────────────────────────

def test_a_retired_leg_stops_contributing():
    v = _votes(momentum=1.0, volume=-1.0)
    w = dict(AL.DEFAULT_LEG_WEIGHTS)
    w["volume"] = 0.0
    with_volume = AL.score_from_legs(v)["score"]
    without = AL.score_from_legs(v, w)["score"]
    assert without > with_volume, "retiring the opposing leg should lift the score"


def test_a_retired_leg_still_reports_that_it_fired():
    """A leg at zero weight must stay OBSERVABLE, which is what lets the loop
    change its mind later. This is the difference from a pillar at zero."""
    w = dict(AL.DEFAULT_LEG_WEIGHTS)
    w["volume"] = 0.0
    s = AL.score_from_legs(_votes(volume=1.0), w)
    assert s["legs_fired"] == 1
    assert s["score"] == pytest.approx(AL.NEUTRAL), "zero weight moves nothing"


def test_reweighting_changes_the_scorer_version():
    """Two different weightings must be distinguishable in the ledger, or
    calibration averages two scorers into one number."""
    a = AL.scorer_version()
    b = AL.scorer_version({**AL.DEFAULT_LEG_WEIGHTS, "momentum": 3.0})
    c = AL.scorer_version(fixed_denominator=False)
    assert len({a, b, c}) == 3


def test_the_legacy_marker_is_distinct_from_any_current_version():
    assert AL.LEGACY_SCORER_VERSION != AL.scorer_version()
    assert AL.LEGACY_SCORER_VERSION != AL.scorer_version(fixed_denominator=False)


# ── signals in, votes out ─────────────────────────────────────────────────

@pytest.mark.parametrize("signal,leg,expected", [
    ("STRONG_BUY", "mean_reversion", 1.0),
    ("SELL", "mean_reversion", -1.0),
    ("STRONG_BULLISH", "momentum", 1.0),
    ("BEARISH", "momentum", -1.0),
    ("UPTREND", "trend", 1.0),
    ("STRONG_DOWNTREND", "trend", -1.0),
])
def test_signal_strings_map_to_signed_votes(signal, leg, expected):
    key = {"mean_reversion": "mean_reversion_signal",
           "momentum": "momentum_signal", "trend": "linreg_signal"}[leg]
    assert AL.votes_from_signals({key: signal})[leg] == expected


def test_an_unrecognised_signal_is_silent_not_bullish():
    """A signal string nobody mapped must cast no vote. Defaulting to bullish
    would let a vocabulary change quietly buy something."""
    v = AL.votes_from_signals({"momentum_signal": "SOMETHING_NEW",
                               "mean_reversion_signal": None})
    assert v["momentum"] == 0.0 and v["mean_reversion"] == 0.0


def test_a_missing_volume_signal_casts_no_vote():
    """Index and FX series carry no volume; the live scorer reports None there."""
    assert AL.votes_from_signals({"volume_price_signal": None})["volume"] == 0.0


# ── the series must equal the live scorer ──────────────────────────────────

def _trend_df(n=300, drift=0.004, seed=7):
    rng = np.random.default_rng(seed)
    px = 100 * np.cumprod(1 + drift + rng.normal(0, 0.01, n))
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                         "Close": px, "Volume": rng.integers(1e6, 5e6, n)},
                        index=idx)


def test_the_series_matches_the_live_scorer_on_the_last_bar():
    """Two copies of the same thresholds is how a backtest comes to measure a
    strategy that is not running. When the live scorer moved to a fixed
    denominator, the series kept returning the vote-ratio: 100 against 64."""
    from backtest.pillars import algo_score_series
    from tools.market_data import compute_algo_signals

    df = _trend_df()
    live = compute_algo_signals(df, {"current_price": float(df["Close"].iloc[-1])})
    assert algo_score_series(df).iloc[-1] == float(live["algo_score"])


def test_the_series_never_looks_ahead():
    """Truncating the frame must not change any earlier value."""
    df = _trend_df()
    full = AL.score_series(df)
    cut = AL.score_series(df.iloc[:-30])
    assert np.allclose(full.iloc[:-30].values, cut.values, equal_nan=True)


def test_leg_series_emits_only_signed_votes():
    legs = AL.leg_series(_trend_df())
    assert set(legs.columns) == set(AL.LEGS)
    for leg in AL.LEGS:
        assert set(np.unique(legs[leg].values)) <= {-1.0, 0.0, 1.0}


def test_the_series_stays_in_range():
    s = AL.score_series(_trend_df())
    assert s.between(0, 100).all()
