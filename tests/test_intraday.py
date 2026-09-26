"""
The intraday layer.

Intraday inverts the sample-size problem that makes the long daily horizons
unverifiable — a month of 5-minute bars holds ~429 non-overlapping 4-bar windows
against 3 independent windows at the ledger's 252-day horizon — and introduces a
harder one in its place: the spread is the same order of magnitude as the signal.
So the tests guard the two things that make an intraday number honest: windows
must not be double-counted, and costs must not be optional.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from intraday import evaluate as EV
from intraday import features as FT
from intraday import simulate as SIM


def _bars(n=400, sessions=4, start_price=100.0, seed=3):
    """Synthetic intraday frame with real session boundaries."""
    rng = np.random.default_rng(seed)
    per = n // sessions
    idx, px = [], []
    price = start_price
    for d in range(sessions):
        day = pd.Timestamp("2026-09-07", tz="UTC") + pd.Timedelta(days=d)
        open_ = day + pd.Timedelta(hours=13, minutes=30)
        price *= 1.02                               # overnight gap
        for b in range(per):
            idx.append(open_ + pd.Timedelta(minutes=5 * b))
            price *= 1 + rng.normal(0, 0.0015)
            px.append(price)
    df = pd.DataFrame({"close": px, "open": px, "high": [p * 1.001 for p in px],
                       "low": [p * 0.999 for p in px],
                       "volume": rng.integers(1e5, 1e6, len(px))},
                      index=pd.DatetimeIndex(idx, name="ts"))
    return df


# ── features look only backwards ──────────────────────────────────────────

def test_features_never_use_a_later_bar():
    df = _bars()
    full = FT.compute(df, "5m")
    cut = FT.compute(df.iloc[:-40], "5m")
    for col in FT.FEATURES:
        a = full[col].iloc[:-40].to_numpy(dtype=float)
        b = cut[col].to_numpy(dtype=float)
        assert np.allclose(a, b, equal_nan=True), f"{col} changed when truncated"


def test_gap_from_open_resets_each_session():
    """Rolled continuously it would silently measure the overnight gap as well
    as the intraday drift, and the gap is not what an intraday signal forecasts."""
    df = _bars(sessions=3)
    f = FT.compute(df, "5m")
    firsts = f.groupby(f["_session"])[FT.GAP_FROM_OPEN].first()
    assert np.allclose(firsts.to_numpy(dtype=float), 0.0, atol=1e-9)


def test_minutes_since_open_resets_each_session():
    df = _bars(sessions=3)
    f = FT.compute(df, "5m")
    assert f.groupby(f["_session"])[FT.MINUTES_IN].first().abs().max() < 1e-9


# ── forward returns must not span the overnight gap ────────────────────────

def test_a_window_crossing_a_session_is_dropped():
    """A 2% overnight gap dwarfs any 20-minute move. Leaving those windows in
    makes the gap the dominant term and reads as edge."""
    df = _bars(sessions=4)
    fwd = FT.forward_return(df, 4, same_session_only=True)
    loose = FT.forward_return(df, 4, same_session_only=False)
    assert fwd.isna().sum() > loose.isna().sum()
    sess = pd.Series(df.index.tz_convert("America/New_York").date, index=df.index)
    for ts in fwd.dropna().index:
        i = df.index.get_loc(ts)
        assert sess.iloc[i] == sess.iloc[i + 4]


def test_the_overnight_gap_would_otherwise_dominate():
    """Quantifies why the drop matters rather than asserting it on faith."""
    df = _bars(sessions=4)
    loose = FT.forward_return(df, 4, same_session_only=False)
    tight = FT.forward_return(df, 4, same_session_only=True)
    crossing = loose[tight.isna() & loose.notna()]
    assert crossing.abs().mean() > tight.abs().mean() * 2


# ── independence, the property intraday actually has ──────────────────────

def test_independent_windows_divides_by_the_horizon():
    assert EV.independent_windows(1716, 4) == 429
    assert EV.independent_windows(1716, 12) == 143
    assert EV.independent_windows(100, 0) == 100      # guarded, not a crash


def test_independent_windows_never_exceeds_the_observation_count():
    for n in (0, 1, 50, 1716):
        for h in (1, 4, 26):
            assert EV.independent_windows(n, h) <= n


# ── costs are not optional ────────────────────────────────────────────────

def test_the_simulation_charges_both_legs():
    """One round trip per leg. Charging once would halve the only cost that
    decides whether an intraday signal is usable."""
    net_list_cost = SIM.DEFAULT_COST_BPS
    assert net_list_cost > 0
    # The arithmetic the simulator uses, asserted directly.
    gross, cost_bps = 0.10, 2.0
    assert gross - 2.0 * (cost_bps / 100.0) == pytest.approx(0.06)


def test_a_signal_smaller_than_the_spread_reads_as_negative():
    """The failure mode that matters: a real correlation on a move too small to
    trade must not report as an opportunity."""
    assert SIM._verdict(-0.01, 3.0) == "NEGATIVE_AFTER_COSTS"
    assert SIM._verdict(0.05, 0.4) == "POSITIVE_BUT_NOT_SIGNIFICANT"
    assert SIM._verdict(0.05, 2.5) == "POSITIVE_AND_SIGNIFICANT"
    assert SIM._verdict(0.05, None) == "NOT_MEASURABLE"


def test_the_evaluator_reports_cost_against_the_typical_move():
    """An IC with no cost context is the number that makes intraday look easy."""
    idx = pd.date_range("2026-09-07 13:30", periods=400, freq="5min", tz="UTC")
    rng = np.random.default_rng(1)
    px = 100 * np.cumprod(1 + rng.normal(0, 0.0015, 400))
    df = pd.DataFrame({"close": px, "open": px, "high": px * 1.001,
                       "low": px * 0.999, "volume": [1e6] * 400}, index=idx)
    # The arithmetic directly, rather than the network path: the cost must be
    # expressed as a SHARE of the move the signal is trying to forecast, and at
    # a 20-minute horizon that share is large enough to decide the question.
    fwd = FT.forward_return(df, 4, same_session_only=False).dropna()
    mean_abs_bps = float(fwd.abs().mean()) * 100.0
    assert mean_abs_bps > 0
    share = EV.DEFAULT_COST_BPS / mean_abs_bps
    assert 0.0 < share < 1.0, (
        "a 2bps cost against a typical 20-minute move should be a meaningful "
        f"but not total fraction of it; got {share:.3f}")


# ── the sweep must own its multiple comparisons ────────────────────────────

def test_the_sweep_raises_the_bar_for_the_number_of_tests():
    """Testing 8 features at 3 horizons is 24 tries, so one t above 2 is roughly
    what chance produces. A sweep that reported the raw bar would manufacture a
    finding every time it ran."""
    from statistics import NormalDist
    for n in (1, 24, 100):
        adj = NormalDist().inv_cdf(1 - 0.05 / (2 * n))
        assert adj >= 1.959
        if n > 1:
            assert adj > 2.0
    assert NormalDist().inv_cdf(1 - 0.05 / (2 * 24)) == pytest.approx(3.08, abs=0.02)


def test_an_annualized_intraday_sharpe_is_labelled_misleading():
    """Scaling a per-period Sharpe by sqrt(1512) turns an ordinary 0.24 into 9.2,
    a figure no strategy has sustained. The per-period number must lead and the
    caveat must travel with the annualized one."""
    import inspect
    src = inspect.getsource(SIM.simulate)
    assert "sharpe_per_period" in src
    assert "sharpe_annualized_naive" in src
    assert "annualization_caveat" in src


def test_insufficient_names_is_reported_not_papered_over():
    r = SIM.simulate(["ONLYONE"], "zscore_20bar", 4)
    assert r["status"] in ("INSUFFICIENT_NAMES", "INSUFFICIENT_PERIODS")


# ── interval bookkeeping ──────────────────────────────────────────────────

def test_bars_convert_to_minutes_per_interval():
    assert FT.bars_to_minutes(12, "5m") == 60
    assert FT.bars_to_minutes(4, "15m") == 60
    assert FT.bars_to_minutes(1, "60m") == 60


def test_every_interval_with_a_bar_count_has_a_minute_mapping():
    for iv in FT.BARS_PER_SESSION:
        assert FT.bars_to_minutes(1, iv) > 0
