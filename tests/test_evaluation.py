"""
The evaluation pipeline and the feedback edges it found broken.

Offline and deterministic. Each ledger-backed test gets its own temp database
(predictions are immutable, so tests cannot share one).

What is load-bearing here:
  * the probability FRAME — p_up is graded against "did it rise", P(call right)
    against "was the call right"; mixing them scored every right bearish call
    as a confident miss (the bug this file pins);
  * the scorecard's rules cannot drift (t >= 2, 20 independent windows);
  * a baseline never sees the future (trailing base rate);
  * P(beat SPY) is refused unless it beats the base rate out of sample, and is
    never stamped onto a back-dated call.
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def ledger(monkeypatch):
    from data import ledger as dl, store
    from data import prediction_ledger as pl
    tmp = Path(tempfile.mkdtemp())
    prev = (store.DB_PATH, getattr(store, "_DB_PATH", None), pl._db_override, dl._db_override)
    store._DB_PATH = tmp / "s.db"
    store.DB_PATH = store._DB_PATH
    dl.set_db_path(tmp / "l.db")
    pl.set_db_path(tmp / "s.db")
    monkeypatch.delenv("LEDGER_ROLE", raising=False)
    from intelligence import outperform
    from evaluation import report
    outperform.clear_cache()
    report.clear_cache()
    yield pl
    store.DB_PATH, store._DB_PATH = prev[0], prev[1]
    pl.set_db_path(prev[2])
    dl.set_db_path(prev[3])
    outperform.clear_cache()
    report.clear_cache()


def _rec(ticker, day, action="BUY", composite=60.0, p_up=None, p_beat=None, conf="LOW", edge=0.4):
    rec = {
        "ticker": ticker, "generated_at": f"{day}T00:00:00", "current_price": 100.0,
        "action": action, "time_horizon_days": 20, "sector": "Technology", "regime": "LOW",
        "benchmark": "SPY", "composite": composite,
        "confidence": {"statistical_edge": {"level": conf, "score": edge, "checks": {}}},
        "pillars": {"technical": {"score": composite}, "algo": {"score": 50.0},
                    "fundamentals": {"score": 100 - composite}},
        "claims": {},
        "horizon_probabilities": p_up,
    }
    if p_beat:
        rec["outperform_probabilities"] = p_beat
    return rec


def _outcome(pl, sid, h, raw, excess, matured_on):
    conn = pl._conn()
    try:
        pl._upsert_outcome(conn, sid, h, {
            "matured": True, "as_of_date": matured_on, "price_at_horizon": 100 * (1 + raw / 100),
            "raw_return_pct": raw, "benchmark_return_pct": raw - excess, "excess_return_pct": excess,
            "mae_pct": min(raw, 0), "mfe_pct": max(raw, 0), "direction_correct": None, "brier": None})
        conn.commit()
    finally:
        conn.close()


def _days(n, start="2025-01-02"):
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ── 1. The probability frame ──────────────────────────────────────────────

def _prices(path):
    idx = pd.bdate_range("2025-01-02", periods=len(path))
    return pd.Series(path, index=idx, dtype=float)


def test_brier_for_a_bearish_call_uses_the_complement_of_p_up(ledger):
    pl = ledger
    falling = _prices([100, 95] + [95] * 300)
    out = pl.evaluate_outcomes("2025-01-02", "SELL", falling, None, horizon_probabilities={1: 0.3})
    # Right call (price fell), stated P(call right) = 1 - 0.3 = 0.7 -> (0.7-1)^2.
    assert out[1]["direction_correct"] == 1
    assert out[1]["brier"] == pytest.approx(0.09, abs=1e-6)


def test_brier_for_a_bullish_call_uses_p_up_itself(ledger):
    pl = ledger
    rising = _prices([100, 105] + [105] * 300)
    out = pl.evaluate_outcomes("2025-01-02", "BUY", rising, None, horizon_probabilities={1: 0.7})
    assert out[1]["brier"] == pytest.approx(0.09, abs=1e-6)


def test_a_wrong_bearish_call_is_penalised_not_rewarded(ledger):
    pl = ledger
    rising = _prices([100, 105] + [105] * 300)
    out = pl.evaluate_outcomes("2025-01-02", "REDUCE", rising, None, horizon_probabilities={1: 0.3})
    # Wrong call stated at 0.7 -> (0.7-0)^2 = 0.49. Before the fix: (0.3-0)^2 = 0.09.
    assert out[1]["brier"] == pytest.approx(0.49, abs=1e-6)


def test_calibration_pairs_grade_p_up_against_the_price_for_every_action(ledger):
    pl = ledger
    from intelligence.calibration import _pairs_for_horizon
    s_sell = pl.freeze_prediction(_rec("MSFT", "2025-01-02", "SELL", p_up={1: 0.3}))
    s_hold = pl.freeze_prediction(_rec("AAPL", "2025-01-02", "HOLD", p_up={1: 0.55}))
    _outcome(pl, s_sell, 1, -2.0, -1.0, "2025-01-03")     # fell: the SELL was right
    _outcome(pl, s_hold, 1, 1.0, 0.5, "2025-01-03")       # rose
    pairs = sorted(_pairs_for_horizon(1, "all"))
    assert pairs == [(0.3, 0.0, "2025-01-03"), (0.55, 1.0, "2025-01-03")]


def test_the_ledger_freezes_the_uncalibrated_probability():
    from intelligence.prediction_engine import frozen_probabilities
    fc = {"horizons": {"1d": {"horizon_days": 1, "p_up": 0.42, "p_up_uncalibrated": 0.61},
                       "5d": {"horizon_days": 5, "p_up": 0.58}}}
    assert frozen_probabilities(fc) == {1: 0.61, 5: 0.58}
    assert frozen_probabilities(None) == {}


def test_a_call_older_than_the_price_series_is_not_graded(ledger):
    pl = ledger
    series = pd.Series(np.linspace(100, 120, 300), index=pd.bdate_range("2024-10-01", periods=300))
    out = pl.evaluate_outcomes("2022-01-03", "BUY", series, None)
    assert all(o["matured"] is False for o in out.values())
    assert out[20]["reason"] == "no price history at the call date"
    weekend = pl.evaluate_outcomes("2024-09-28", "BUY", series, None)   # Saturday -> Tuesday
    assert weekend[1]["matured"] is True


def test_history_window_reaches_the_oldest_call():
    from data.prediction_ledger import history_period
    today = date.today()
    assert history_period((today - timedelta(days=30)).isoformat()) == "1y"
    assert history_period((today - timedelta(days=500)).isoformat()) == "2y"
    assert history_period((today - timedelta(days=1000)).isoformat()) == "5y"
    assert history_period((today - timedelta(days=3000)).isoformat()) == "10y"
    assert history_period((today - timedelta(days=5000)).isoformat()) == "max"


def test_refresh_downloads_enough_history_and_skips_todays_bar(ledger, monkeypatch):
    pl = ledger
    today = date.today()
    old = (today - timedelta(days=1000)).isoformat()
    sid_old = pl.freeze_prediction(_rec("MSFT", old, "BUY"))
    # A call one session before today: its 1d horizon is today's (provisional) bar.
    # The last bar is dated today (whatever weekday the suite runs on).
    idx = pd.bdate_range(end=pd.Timestamp(today - timedelta(days=1)), periods=599).append(
        pd.DatetimeIndex([pd.Timestamp(today)]))
    prev_session = str(idx[-2].date())
    sid_new = pl.freeze_prediction(_rec("MSFT", prev_session, "BUY"))
    asked = []

    def fake(t, period="6mo"):
        asked.append((t, period))
        return pd.DataFrame({"Close": np.linspace(100, 200, len(idx))}, index=idx)
    import tools.market_data as md
    monkeypatch.setattr(md, "fetch_price_history", fake)
    pl.refresh_outcomes()
    assert ("MSFT", "5y") in asked and ("SPY", "5y") in asked
    conn = pl._conn()
    try:
        m = {r[0]: r[1] for r in conn.execute(
            "SELECT snapshot_id, matured FROM prediction_outcomes WHERE horizon_days=1")}
    finally:
        conn.close()
    assert m[sid_new] == 0            # today's bar may not be final yet
    assert m[sid_old] == 0            # 1000 days ago is before this ~840-day series starts


# ── 2. Statistics ─────────────────────────────────────────────────────────

def test_spearman_and_ranks():
    from evaluation.stats import ranks, spearman
    assert ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2], [1, 2]) is None


def test_newey_west_with_no_lag_is_the_plain_standard_error():
    from evaluation.stats import newey_west_se
    xs = [1.0, 2.0, 4.0, 3.0, 5.0]
    m = sum(xs) / 5
    plain = (sum((x - m) ** 2 for x in xs) / 5 / 5) ** 0.5
    assert newey_west_se(xs, 0) == pytest.approx(plain)


def test_overlap_correction_shrinks_t_for_autocorrelated_series():
    from evaluation.stats import t_stat
    rng = random.Random(3)
    base = [rng.gauss(0.05, 1) for _ in range(60)]
    smooth = [sum(base[i:i + 5]) / 5 for i in range(55)]   # MA(4): what 5d overlap produces
    assert abs(t_stat(smooth, 4)) < abs(t_stat(smooth, 0))


# ── 3. The scorecard's rules and metrics ──────────────────────────────────

def test_rules_are_pinned():
    from evaluation import scorecard as S
    from intelligence.calibration import MIN_EFFECTIVE_OBS
    assert S.T_SIGNIFICANT == 2.0
    assert S.MIN_WINDOWS == MIN_EFFECTIVE_OBS == 20
    assert S.MIN_NAMES_PER_DATE == 8
    assert S.MIN_DATES == 5


def _synthetic(dates, names=12, skill=0.0, market=0.0, seed=1, h=1):
    """Records as scorecard.load() returns them: composite with `skill` of
    signal in excess return, on top of a common market move."""
    rng = random.Random(seed)
    recs = []
    for d in dates:
        mkt = market + rng.gauss(0, 0.5)
        for i in range(names):
            comp = rng.uniform(30, 80)
            excess = skill * (comp - 55) / 10 + rng.gauss(0, 1)
            raw = mkt + excess
            side = 1 if comp >= 60 else (-1 if comp < 45 else 0)
            recs.append({"ticker": f"N{i:02d}", "action": {1: "BUY", -1: "SELL", 0: "HOLD"}[side],
                         "side": side, "call_date": d,
                         "outcome_date": (date.fromisoformat(d) + timedelta(days=h + 1)).isoformat(),
                         "conf": "MEDIUM", "edge_score": 0.8, "sector": "x", "composite": comp,
                         "pillars": {"technical": comp, "algo": rng.uniform(30, 80)},
                         "p_up": 0.6 if side > 0 else 0.4, "p_beat": None, "raw": raw,
                         "excess": excess, "went_up": 1.0 if raw > 0 else 0.0,
                         "beat": 1.0 if excess > 0 else 0.0})
    return recs


def test_a_real_ranking_signal_over_enough_windows_is_an_edge():
    from evaluation import scorecard as S
    recs = _synthetic(_days(40), skill=0.6, seed=2)
    card = S.horizon_scorecard(recs, 1)
    assert card["ranking"]["rank_ic"]["mean"] > 0.2
    assert card["verdicts"]["ranking"]["verdict"] == "EDGE"
    assert card["pillars"]["technical"]["mean"] > 0.2        # the pillar carrying the signal
    assert abs(card["pillars"]["algo"]["mean"]) < 0.15       # the one that is noise


def test_noise_is_not_an_edge():
    from evaluation import scorecard as S
    card = S.horizon_scorecard(_synthetic(_days(40), skill=0.0, seed=4), 1)
    assert card["verdicts"]["ranking"]["verdict"] in ("NO_EDGE", "PROMISING")
    assert card["verdicts"]["ranking"]["verdict"] != "EDGE"


def test_a_signal_on_too_few_independent_windows_is_only_promising():
    from evaluation import scorecard as S
    # 30 consecutive days graded at 20d: lots of dates, 1-2 independent windows.
    card = S.horizon_scorecard(_synthetic(_days(30), skill=0.8, seed=5, h=20), 20)
    assert card["ranking"]["rank_ic"]["independent_windows"] < 20
    assert card["verdicts"]["ranking"]["verdict"] == "PROMISING"


def test_too_few_dates_is_insufficient():
    from evaluation import scorecard as S
    card = S.horizon_scorecard(_synthetic(_days(3), skill=1.0), 1)
    assert card["verdicts"]["ranking"]["verdict"] == "INSUFFICIENT"


def test_a_falling_market_separates_hit_on_price_from_hit_vs_spy():
    from evaluation import scorecard as S
    recs = _synthetic(_days(30), skill=0.8, market=-3.0, seed=6)
    d = S.direction(recs, 1)
    assert d["share_of_calls_where_stock_rose"] < 0.2
    assert d["hit_vs_spy"]["rate"] > d["hit_on_price"]["rate"] - 0.05
    assert d["by_action"]["BUY"]["hit_on_price"] < 0.3       # every long lost on price
    assert d["by_action"]["BUY"]["hit_vs_spy"] > 0.5         # but beat the market


def test_the_trailing_base_rate_never_sees_the_future():
    from evaluation.scorecard import _trailing_rate
    recs = [{"outcome_date": "2025-01-10", "went_up": 1.0},
            {"outcome_date": "2025-01-20", "went_up": 0.0},
            {"outcome_date": "2025-01-30", "went_up": 0.0}]
    rate = _trailing_rate(recs, "went_up")
    assert rate("2025-01-05") is None          # nothing had matured yet
    assert rate("2025-01-15") == 1.0           # only the 01-10 outcome was known
    assert rate("2025-01-25") == 0.5
    assert rate("2025-01-20") == 1.0           # maturing ON the call date is not yet known


def test_an_overconfident_label_is_reported_as_such():
    from evaluation import scorecard as S
    recs = _synthetic(_days(20), skill=0.0, seed=7)
    conf = {c["level"]: c for c in S.confidence(recs, 1)}
    assert conf["MEDIUM"]["claimed"] == pytest.approx(0.9)
    assert conf["MEDIUM"]["overclaim_pts"] > 25


def test_a_label_with_a_handful_of_calls_never_makes_the_headline():
    from evaluation import scorecard as S
    from evaluation.report import headline
    recs = _synthetic(_days(20), skill=0.0, seed=9)
    for x in recs[:2]:
        x["conf"], x["edge_score"] = "HIGH", 1.0           # 2 calls claiming 100%
    lines = headline(S.horizon_scorecard(recs, 1))
    assert not any("HIGH claimed" in line for line in lines)
    assert any("MEDIUM claimed" in line for line in lines)


def test_probability_skill_against_no_hindsight_baselines():
    from evaluation import scorecard as S
    recs = _synthetic(_days(30), skill=0.0, seed=8)
    for x in recs:
        x["p_up"] = 0.9          # wildly overconfident and uninformative
    p = S.probability(recs, 1)
    assert p["brier"] > p["brier_always_50pct"]
    assert p["skill_vs_50pct"] < 0
    assert p["reliability"] and p["reliability"][-1]["stated"] == pytest.approx(0.9)


# ── 4. P(beat SPY) ────────────────────────────────────────────────────────

def _pairs(n_dates, informative, seed=0, per_day=10):
    rng = random.Random(seed)
    out = []
    for d in _days(n_dates, "2024-01-02"):
        for _ in range(per_day):
            c = rng.uniform(20, 90)
            p = 0.2 + 0.6 * (c - 20) / 70 if informative else 0.4
            out.append((c, 1.0 if rng.random() < p else 0.0, d))
    return out


def test_outperform_map_is_applied_only_when_it_beats_the_base_rate():
    from intelligence.outperform import fit_from_pairs
    good = fit_from_pairs(_pairs(120, True, 1), 1)
    assert good["applied"] and good["brier_model"] < good["brier_base_rate"]
    noise = fit_from_pairs(_pairs(120, False, 2), 1)
    assert not noise["applied"]
    assert noise["reason"] == "no_out_of_sample_skill_vs_base_rate"


def test_outperform_needs_independent_windows_not_rows():
    from intelligence.outperform import fit_from_pairs
    thin = fit_from_pairs(_pairs(12, True, 3, per_day=60), 1)   # 720 rows, 12 dates
    assert not thin["applied"]
    assert thin["reason"].startswith("insufficient_independent_windows")


def test_outperform_probabilities_are_monotone_and_absent_without_a_model():
    from intelligence.outperform import fit_from_pairs, probabilities
    m = {1: fit_from_pairs(_pairs(120, True, 4), 1)}
    lo, hi = probabilities(30, m)[1], probabilities(85, m)[1]
    assert lo < hi
    assert probabilities(60, {1: {"applied": False}}) is None
    assert probabilities(None, m) is None


def test_outperform_probabilities_are_frozen_and_absent_ones_change_no_hash(ledger):
    pl = ledger
    a = pl.freeze_prediction(_rec("MSFT", "2025-01-02"))
    again = pl.freeze_prediction(_rec("MSFT", "2025-01-02"))
    assert a == again
    assert "outperform_probabilities" not in json.loads(pl.get_snapshot(a)["frozen_json"])
    b = pl.freeze_prediction(_rec("MSFT", "2025-01-03", p_beat={1: 0.47}))
    assert json.loads(pl.get_snapshot(b)["frozen_json"])["outperform_probabilities"] == {"1": 0.47}


def test_heartbeat_states_p_beat_but_never_on_a_back_dated_run():
    import agents.heartbeat as hb
    from intelligence.outperform import fit_from_pairs
    models = {1: fit_from_pairs(_pairs(120, True, 5), 1)}
    assert models[1]["applied"]
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    df = pd.DataFrame({"Close": [50.0 + i * 0.1 for i in range(300)]}, index=idx)

    def rec_fn(t):
        return ({"ticker": t, "current_price": 79.9, "action": "BUY", "composite": 72.0,
                 "pillars": {"technical": {"score": 70, "confidence": 1.0},
                             "algo": {"score": 66, "confidence": 1.0},
                             "fundamentals": {"score": 75, "confidence": 1.0}},
                 "levels": {"atr_14": 2.0}, "algo_signals": {"algo_score": 66}}, df)

    frozen = []
    orig_freeze, orig_af = hb.pl.freeze_prediction, hb.already_frozen
    hb.pl.freeze_prediction = lambda rec: (frozen.append(dict(rec)) or "sid")
    hb.already_frozen = lambda t, d: False
    try:
        live = hb.forecast_and_freeze("MSFT", recommend_fn=rec_fn, outperform_models=models)
        back = hb.forecast_and_freeze("MSFT", recommend_fn=rec_fn, outperform_models=models,
                                      as_of="2025-03-03")
    finally:
        hb.pl.freeze_prediction, hb.already_frozen = orig_freeze, orig_af
    assert live["status"] == "done" and set(live["p_beat_spy"]) == {1}
    assert "outperform_probabilities" in frozen[0]
    assert back["status"] == "done" and back["p_beat_spy"] is None
    assert "outperform_probabilities" not in frozen[1]


# ── 5. End to end on a ledger ─────────────────────────────────────────────

def _populate(pl, n_dates=30, names=10, seed=11):
    rng = random.Random(seed)
    for d in _days(n_dates):
        for i in range(names):
            comp = rng.uniform(30, 80)
            action = "BUY" if comp >= 60 else ("SELL" if comp < 45 else "HOLD")
            sid = pl.freeze_prediction(_rec(f"N{i:02d}", d, action, comp, p_up={1: 0.55, 5: 0.55},
                                            p_beat={1: round(0.3 + comp / 200, 3)}))
            excess = 0.5 * (comp - 55) / 10 + rng.gauss(0, 1)
            nxt = (date.fromisoformat(d) + timedelta(days=2)).isoformat()
            _outcome(pl, sid, 1, excess - 0.4, excess, nxt)


def test_report_end_to_end_and_history(ledger, monkeypatch):
    pl = ledger
    _populate(pl)
    from evaluation.history import record, series
    from evaluation.report import build, format_text
    rep = build((1, 5), "live", use_cache=False)
    c1 = rep["horizons"][1]
    assert c1["coverage"]["calls"] == 300
    assert c1["ranking"]["rank_ic"]["mean"] > 0.1
    assert c1["p_beat_spy"]["n"] == 300                      # frozen P(beat SPY) is graded
    assert rep["horizons"][5]["coverage"]["calls"] == 0      # nothing matured at 5d
    assert any("1d ranking" in line for line in rep["headline"])
    assert "PREDICTION SCORECARD" in format_text(rep)
    assert record(rep, "2025-03-01")["recorded"] > 0
    assert series("rank_ic", 1)[0]["value"] == c1["ranking"]["rank_ic"]["mean"]
    monkeypatch.setenv("LEDGER_ROLE", "secondary")
    assert record(rep, "2025-03-02")["recorded"] == 0        # a secondary ledger records nothing


def test_grading_reaches_every_unmatured_call_not_just_the_newest_500(ledger):
    pl = ledger
    days = _days(130, "2024-01-02")
    for i in range(5):
        for d in days:
            pl.freeze_prediction(_rec(f"N{i:02d}", d, "BUY", p_up={1: 0.6}))
    assert len(pl.list_snapshots(limit=None)) == 650
    prices = pd.Series(np.linspace(100, 130, 400), index=pd.bdate_range("2024-01-01", periods=400))
    res = pl.refresh_outcomes(fetch_fn=lambda t: prices)
    assert res["snapshots_evaluated"] == 650
    conn = pl._conn()
    try:
        oldest = conn.execute(
            """SELECT o.matured FROM prediction_outcomes o JOIN prediction_snapshots s USING(snapshot_id)
                WHERE s.created_at LIKE '2024-01-02%' AND o.horizon_days = 60""").fetchall()
    finally:
        conn.close()
    assert oldest and all(r[0] == 1 for r in oldest)
    # A second pass skips what can no longer move (every horizon matured).
    again = pl.refresh_outcomes(fetch_fn=lambda t: prices)
    assert again["snapshots_evaluated"] < 650


def test_quarantined_calls_never_reach_the_scorecard(ledger):
    pl = ledger
    sid = pl.freeze_prediction(_rec("TEST", "2025-01-02", p_up={1: 0.9}))   # synthetic ticker
    _outcome(pl, sid, 1, 1.0, 1.0, "2025-01-03")
    from evaluation.scorecard import load
    assert load(1, "live") == []


def test_api_and_mcp(ledger):
    pl = ledger
    _populate(pl, n_dates=8)
    from web.app import app
    c = app.test_client()
    r = c.get("/api/evaluation?horizons=1&fresh=1")
    assert r.status_code == 200 and r.get_json()["horizons"]["1"]["coverage"]["calls"] == 80
    assert c.get("/api/evaluation?horizons=7").status_code == 400
    assert c.get("/api/evaluation?source=everything").status_code == 400
    assert c.get("/api/evaluation/history?metric=nope").status_code == 400
    from stock_analysis.mcp_server import call_tool
    out = call_tool("prediction_scorecard", {"horizons": [1]})
    assert not out["isError"] and out["structuredContent"]["headline"]
