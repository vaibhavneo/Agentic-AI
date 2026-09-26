"""
The self-improvement loop.

A loop that tunes a system on its own outcome history is a machine for
overfitting unless something stops it, so most of what is asserted here is
REFUSAL. A test suite for this package that mostly checked that promotions
work would be testing the dangerous half.

Everything is synthetic or monkeypatched. Asserting against the live ledger
would make these tests change meaning every time a prediction matures.
"""
from __future__ import annotations

import datetime as dt

import pytest

from selfimprove import config as C
from selfimprove import graph as G
from selfimprove import propose as P
from selfimprove import surface as S
from selfimprove import verify as V


# ── the tunable surface is a whitelist ────────────────────────────────────

def test_an_undeclared_parameter_can_never_be_changed():
    ok, why = S.check_change("risk_veto", "threshold", 0.5, 0.6)
    assert not ok and "not a declared tunable" in why


def test_bounds_are_enforced_in_both_directions():
    t = S.get(S.PILLAR_WEIGHTS, "algo")
    assert not t.in_bounds(t.hi + 0.01)
    assert not t.in_bounds(t.lo - 0.01)


def test_no_pillar_can_be_driven_to_zero():
    """A pillar at zero weight stops contributing, stops generating
    attributable observations, and can therefore never earn its weight back.
    The floor is what keeps the loop able to change its mind."""
    assert S.PILLAR_FLOOR > 0
    for key in S.keys_in(S.PILLAR_WEIGHTS):
        assert S.get(S.PILLAR_WEIGHTS, key).lo > 0


def test_one_promotion_cannot_jump_the_whole_range():
    t = S.get(S.PILLAR_WEIGHTS, "algo")
    assert t.max_step < (t.hi - t.lo) / 2
    assert not t.step_ok(0.40, 0.10)


def test_pillar_weights_must_still_sum_to_one():
    ok, why = S.check_invariant(S.PILLAR_WEIGHTS,
                                {"technical": .4, "algo": .4, "fundamentals": .3})
    assert not ok and "sum to" in why


def test_a_partial_group_cannot_satisfy_a_sum_invariant():
    """Checking only the keys that moved would let two legal edits leave the
    group summing to something other than 1."""
    ok, why = S.check_invariant(S.PILLAR_WEIGHTS, {"algo": 0.5})
    assert not ok and "every key" in why


def test_confidence_levels_are_ordered_semantically_not_alphabetically():
    """Sorted alphabetically, HIGH precedes LOW — which would reject the
    correct map and accept an inverted one."""
    assert S.keys_in(S.CONFIDENCE_MAP) == ["LOW", "MEDIUM", "HIGH"]
    ok, _ = S.check_invariant(S.CONFIDENCE_MAP,
                              {"LOW": .5, "MEDIUM": .6, "HIGH": .7})
    assert ok, "a correctly ordered confidence map was rejected"
    bad, why = S.check_invariant(S.CONFIDENCE_MAP,
                                 {"LOW": .9, "MEDIUM": .6, "HIGH": .7})
    assert not bad and "invert" in why


def test_the_safety_critical_knobs_are_absent_from_the_surface():
    """Named explicitly so that adding one later has to delete a test."""
    for group in ("risk_veto", "action_bands", "evidence_tiers", "asset_class"):
        assert group not in S.groups()


# ── attribution refuses to invent credit ──────────────────────────────────

def _snap(**kw):
    base = {"snapshot_id": "s1", "ticker": "AAA", "created_at": "2026-01-05",
            "action": "BUY", "regime": "MEDIUM", "sector": "Tech",
            "conf_thesis": "HIGH", "conf_data": "HIGH",
            "conf_statistical_edge": "MEDIUM",
            "pillars_json": {"technical": 75.0, "algo": 60.0, "fundamentals": 50.0}}
    base.update(kw)
    return base


def _out(**kw):
    base = {"horizon_days": 20, "matured": 1, "excess_return_pct": 4.0}
    base.update(kw)
    return base


def test_an_unmatured_outcome_is_skipped_not_scored_as_zero():
    """Averaging unknowns as zeros drags every node toward neutral and makes
    the loop confident about nothing."""
    assert G.build(_snap(), _out(matured=0)) is None


def test_a_neutral_pillar_earns_neither_credit_nor_blame():
    g = G.build(_snap(), _out())
    names = {e["name"] for e in g["edges"] if e["kind"] == G.PILLAR}
    assert "fundamentals" not in names, "a pillar at 50 contributed nothing"
    assert {"technical", "algo"} <= names


def test_a_bearish_call_that_worked_is_scored_as_a_hit():
    """The ledger's by_action table reads REDUCE and SELL as losses whenever
    price rose, regardless of the call. Attribution must sign by intent.

    Both frames are asserted together because keeping them apart IS the
    correctness of the module: a bearish pillar that was right about a falling
    market, inside a SELL that was right to sell it.
    """
    bear = _snap(action="SELL",
                 pillars_json={"technical": 20.0, "algo": 30.0})
    g = G.build(bear, _out(excess_return_pct=-5.0))
    assert g["realized"] == -5.0, "the market frame is the raw excess return"
    assert g["realized_call"] > 0, "a SELL followed by a fall is a good call"
    pillars = [e for e in g["edges"] if e["kind"] == G.PILLAR]
    assert pillars
    assert all(e["agreed"] for e in pillars), (
        "bearish pillars were right about a falling market")
    assert all(e["agreed_with_call"] for e in pillars), (
        "and right in the decision's frame too")


def test_a_bearish_pillar_is_not_punished_for_a_correct_short():
    """The regression guard for the frame-mixing bug: comparing a market-frame
    tilt to a call-frame outcome scored every correct bearish pillar as a
    miss, which would drive the loop to down-weight the signals that worked."""
    bear = _snap(action="SELL", pillars_json={"technical": 10.0})
    g = G.build(bear, _out(excess_return_pct=-8.0))
    edge = next(e for e in g["edges"] if e["name"] == "technical")
    assert edge["tilt"] < 0, "score 10 is a bearish tilt"
    assert edge["agreed"] is True


def test_a_hold_is_not_attributed_at_all():
    assert G.build(_snap(action="HOLD"), _out()) is None


def test_decision_confidence_is_the_weakest_leg_not_the_strongest():
    """A high-conviction thesis resting on absent data is not a
    high-confidence call."""
    assert G._decision_confidence(
        {"conf_thesis": "HIGH", "conf_data": "LOW",
         "conf_statistical_edge": "HIGH"}) == "LOW"


def test_contribution_scales_with_weight_not_just_score():
    """The distinction the whole graph exists for: the same score inside a
    small weight moved the decision less."""
    heavy = G.build(_snap(), _out(), weights={"technical": 0.9, "algo": 0.05,
                                              "fundamentals": 0.05})
    light = G.build(_snap(), _out(), weights={"technical": 0.05, "algo": 0.9,
                                              "fundamentals": 0.05})
    def _c(g, name):
        return next(e["contribution"] for e in g["edges"] if e["name"] == name)
    assert _c(heavy, "technical") > _c(light, "technical")


# ── the gate ──────────────────────────────────────────────────────────────

def _graphs(n, start="2024-01-01", step_days=7, realized=lambda i: 1.0,
            tilt=lambda i: 0.5):
    d0 = dt.date.fromisoformat(start)
    out = []
    for i in range(n):
        out.append({
            "snapshot_id": f"s{i}", "ticker": "AAA",
            "as_of": (d0 + dt.timedelta(days=step_days * i)).isoformat(),
            "horizon_days": 20, "action": "BUY", "direction": 1.0,
            "realized": realized(i),
            "edges": [
                {"node": "pillar:technical", "kind": G.PILLAR,
                 "name": "technical", "tilt": tilt(i), "weight": 0.4,
                 "contribution": tilt(i) * 0.4, "agreed": realized(i) > 0},
                {"node": "pillar:algo", "kind": G.PILLAR, "name": "algo",
                 "tilt": -tilt(i), "weight": 0.4,
                 "contribution": -tilt(i) * 0.4, "agreed": realized(i) < 0},
                {"node": "pillar:fundamentals", "kind": G.PILLAR,
                 "name": "fundamentals", "tilt": tilt(i) * 0.5, "weight": 0.2,
                 "contribution": tilt(i) * 0.1, "agreed": realized(i) > 0},
            ]})
    return out


CUR = {"technical": 0.40, "algo": 0.40, "fundamentals": 0.20}
CAND = {"technical": 0.375, "algo": 0.375, "fundamentals": 0.25}


def test_an_out_of_bounds_candidate_is_refused_before_any_data_is_read():
    r = V.evaluate(S.PILLAR_WEIGHTS, CUR,
                   {"technical": 0.0, "algo": 0.0, "fundamentals": 1.0},
                   20, graphs=_graphs(500))
    assert r["verdict"] == V.REFUSE
    assert r["checks"][0]["check"] == "surface"
    assert r["metric_current"] is None, "data was read despite a surface failure"


def test_thin_evidence_is_refused_however_good_the_apparent_effect():
    r = V.evaluate(S.PILLAR_WEIGHTS, CUR, CAND, 20, graphs=_graphs(12))
    assert r["verdict"] == V.REFUSE
    assert any(c["check"].startswith("evidence") and not c["passed"]
               for c in r["checks"])


def test_overlapping_windows_cannot_pass_as_independent_evidence():
    """200 calls one day apart at a 60-day horizon share almost all of their
    price path. Row count says plenty; independence says almost none."""
    r = V.evaluate(S.PILLAR_WEIGHTS, CUR, CAND, 60,
                   graphs=_graphs(200, step_days=1))
    assert r["verdict"] == V.REFUSE
    assert r["effective_n"] < V.MIN_EFFECTIVE_N
    assert "overlap in time" in r["reason"]


def test_an_effect_inside_the_noise_floor_is_refused():
    r = V.evaluate(S.PILLAR_WEIGHTS, CUR, CAND, 20, graphs=_graphs(400))
    if r["verdict"] == V.REFUSE and r.get("effect") is not None:
        assert abs(r["effect"]) < V.MIN_EFFECT


def test_the_test_window_never_precedes_the_training_window():
    """The single check that makes out-of-sample mean anything."""
    folds = V._purged_time_split(_graphs(400), horizon=20)
    assert folds
    for train, test in folds:
        assert max(g["as_of"] for g in train) < min(g["as_of"] for g in test)


def test_the_purge_gap_is_at_least_one_horizon():
    """Without it, a call made on the last training day is still resolving
    inside the test window and the two sets share a price path."""
    horizon = 20
    folds = V._purged_time_split(_graphs(400, step_days=3), horizon=horizon)
    assert folds
    min_gap = dt.timedelta(days=int(horizon * 365.0 / 252.0))
    for train, test in folds:
        boundary = dt.date.fromisoformat(max(g["as_of"] for g in train))
        earliest = dt.date.fromisoformat(min(g["as_of"] for g in test))
        assert earliest - boundary >= min_gap


def test_a_candidate_that_only_fits_the_early_history_is_refused():
    """The overfitting case, constructed. Tilt predicts the outcome perfectly
    for the first half of history and is pure noise afterwards; any weighting
    tuned on the first half must fail on the held-out second half."""
    n = 400
    flip = n // 2
    graphs = []
    d0 = dt.date.fromisoformat("2023-01-01")
    for i in range(n):
        signal = 1.0 if i % 2 == 0 else -1.0
        realized = signal * 3.0 if i < flip else (1.0 if i % 3 == 0 else -1.0)
        graphs.append({
            "snapshot_id": f"s{i}", "as_of": (d0 + dt.timedelta(days=5 * i)).isoformat(),
            "realized": realized,
            "edges": [
                {"node": "pillar:technical", "kind": G.PILLAR, "name": "technical",
                 "tilt": signal, "weight": 0.4, "contribution": signal * 0.4,
                 "agreed": True},
                {"node": "pillar:algo", "kind": G.PILLAR, "name": "algo",
                 "tilt": 0.01, "weight": 0.4, "contribution": 0.004, "agreed": True},
                {"node": "pillar:fundamentals", "kind": G.PILLAR,
                 "name": "fundamentals", "tilt": 0.01, "weight": 0.2,
                 "contribution": 0.002, "agreed": True},
            ]})
    r = V.evaluate(S.PILLAR_WEIGHTS, CUR,
                   {"technical": 0.45, "algo": 0.35, "fundamentals": 0.20},
                   20, graphs=graphs)
    assert r["verdict"] == V.REFUSE, (
        "a weighting that only works on the training half was promoted")


def test_the_gate_thresholds_are_not_trivially_satisfiable():
    """A guard against the failure mode of quietly relaxing the bar until
    something passes."""
    assert V.MIN_EFFECTIVE_N >= 20
    assert V.MIN_ROWS >= 50
    assert V.MIN_EFFECT > 0
    from intelligence.calibration import MIN_EFFECTIVE_OBS
    assert V.MIN_EFFECTIVE_N >= MIN_EFFECTIVE_OBS, (
        "a weight change must not clear a laxer bar than a calibration fit")


def test_confidence_is_scored_on_brier_not_on_the_tilt_metric():
    """A confidence map changes no ordering, so the tilt metric would report
    exactly zero effect for every candidate and refuse them all for the wrong
    reason."""
    rows = [{"as_of": "2026-01-01", "level": "MEDIUM", "won": True}]
    honest = V.brier_under(rows, {"MEDIUM": 0.55})
    overclaim = V.brier_under(rows, {"MEDIUM": 0.95})
    assert overclaim < honest, "Brier must reward the confident correct call"
    rows_lost = [{"as_of": "2026-01-01", "level": "MEDIUM", "won": False}]
    assert V.brier_under(rows_lost, {"MEDIUM": 0.95}) > \
           V.brier_under(rows_lost, {"MEDIUM": 0.55})


# ── proposals ─────────────────────────────────────────────────────────────

def test_proposals_stay_inside_max_step(monkeypatch):
    monkeypatch.setattr(P, "build_scorecards", lambda h: {
        "pillar:technical": {"n": 100, "effective_n": 40, "ic": -0.20},
        "pillar:algo": {"n": 100, "effective_n": 40, "ic": 0.00},
        "pillar:fundamentals": {"n": 100, "effective_n": 40, "ic": 0.30},
    })
    p = P.pillar_weights(20, current=dict(CUR))
    assert p is not None
    for key, new in p["candidate"].items():
        ok, why = S.check_change(S.PILLAR_WEIGHTS, key, CUR[key], new)
        assert ok, why


def test_tied_evidence_produces_no_proposal(monkeypatch):
    """Without a tie band the loop proposes a change every cycle on the
    strength of the fourth decimal place and churns the weights forever."""
    monkeypatch.setattr(P, "build_scorecards", lambda h: {
        "pillar:technical": {"n": 100, "effective_n": 40, "ic": 0.100},
        "pillar:algo": {"n": 100, "effective_n": 40, "ic": 0.101},
        "pillar:fundamentals": {"n": 100, "effective_n": 40, "ic": 0.102},
    })
    assert P.pillar_weights(20, current=dict(CUR)) is None


def test_a_pillar_with_too_few_observations_cannot_argue(monkeypatch):
    monkeypatch.setattr(P, "build_scorecards", lambda h: {
        "pillar:technical": {"n": 3, "effective_n": 2, "ic": -0.9},
        "pillar:algo": {"n": 2, "effective_n": 1, "ic": 0.9},
        "pillar:fundamentals": {"n": 1, "effective_n": 1, "ic": 0.5},
    })
    assert P.pillar_weights(20, current=dict(CUR)) is None


def test_a_proposal_always_preserves_the_group_invariant(monkeypatch):
    monkeypatch.setattr(P, "build_scorecards", lambda h: {
        "pillar:technical": {"n": 100, "effective_n": 40, "ic": -0.30},
        "pillar:algo": {"n": 100, "effective_n": 40, "ic": 0.05},
        "pillar:fundamentals": {"n": 100, "effective_n": 40, "ic": 0.40},
    })
    p = P.pillar_weights(20, current=dict(CUR))
    ok, why = S.check_invariant(S.PILLAR_WEIGHTS, p["candidate"])
    assert ok, why


# ── config: applying and undoing ──────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    from data import prediction_ledger as PL
    db = tmp_path / "t.db"
    PL.set_db_path(str(db))
    from selfimprove import ledger as L
    C._ready.clear()
    L._ready.clear()
    yield str(db)
    PL.set_db_path(None)
    C._ready.clear()
    L._ready.clear()


def test_an_invalid_group_is_never_written(temp_db):
    res = C.apply(S.PILLAR_WEIGHTS, 20,
                  {"technical": .5, "algo": .5, "fundamentals": .5})
    assert not res["applied"]
    assert C.active(S.PILLAR_WEIGHTS, 20) == C.defaults(S.PILLAR_WEIGHTS)


def test_an_override_is_scoped_to_its_horizon(temp_db):
    C.apply(S.PILLAR_WEIGHTS, 20, CAND)
    assert C.active(S.PILLAR_WEIGHTS, 20)["fundamentals"] == pytest.approx(0.25)
    assert C.active(S.PILLAR_WEIGHTS, 5) == C.defaults(S.PILLAR_WEIGHTS)


def test_revert_restores_the_shipped_defaults(temp_db):
    C.apply(S.PILLAR_WEIGHTS, 20, CAND)
    C.revert(S.PILLAR_WEIGHTS, 20)
    assert C.active(S.PILLAR_WEIGHTS, 20) == C.defaults(S.PILLAR_WEIGHTS)


def test_a_rollback_does_not_erase_its_own_cause(temp_db):
    """A system whose rollbacks delete their history has a past nobody can
    reconstruct."""
    C.apply(S.PILLAR_WEIGHTS, 20, CAND, proposal_id="p1")
    C.revert(S.PILLAR_WEIGHTS, 20, proposal_id="p1")
    assert len(C.history(S.PILLAR_WEIGHTS)) >= 2


def test_config_history_is_append_only(temp_db):
    import sqlite3
    from data import prediction_ledger as PL
    C.apply(S.PILLAR_WEIGHTS, 20, CAND)
    conn = sqlite3.connect(PL._db())
    with pytest.raises(sqlite3.Error):
        conn.execute("DELETE FROM tunable_config_history")
    conn.close()


# ── the improvement ledger ────────────────────────────────────────────────

def test_the_improvement_ledger_is_append_only(temp_db):
    import sqlite3
    from data import prediction_ledger as PL
    from selfimprove import ledger as L
    L.record({"group": S.PILLAR_WEIGHTS, "horizon_days": 20, "current": CUR,
              "candidate": CAND, "verdict": V.REFUSE, "reason": "thin"})
    conn = sqlite3.connect(PL._db())
    with pytest.raises(sqlite3.Error):
        conn.execute("DELETE FROM improvement_proposals")
    conn.close()


def test_a_recorded_verdict_cannot_be_rewritten(temp_db):
    import sqlite3
    from data import prediction_ledger as PL
    from selfimprove import ledger as L
    L.record({"group": S.PILLAR_WEIGHTS, "horizon_days": 20, "current": CUR,
              "candidate": CAND, "verdict": V.REFUSE, "reason": "thin"})
    conn = sqlite3.connect(PL._db())
    with pytest.raises(sqlite3.Error):
        conn.execute("UPDATE improvement_proposals SET verdict='PROMOTE'")
    conn.close()


def test_refusals_are_recorded_not_only_promotions(temp_db):
    """A loop that writes down only its successes looks monotonically
    improving while discarding the evidence that it mostly cannot."""
    from selfimprove import ledger as L
    L.record({"group": S.PILLAR_WEIGHTS, "horizon_days": 20, "current": CUR,
              "candidate": CAND, "verdict": V.REFUSE, "reason": "too thin"})
    s = L.summary()
    assert s["by_verdict"].get(V.REFUSE) == 1
    assert s["top_refusal_reasons"][0]["reason"] == "too thin"


# ── the loop end to end ───────────────────────────────────────────────────

def test_a_dry_run_changes_nothing(temp_db):
    from selfimprove.loop import cycle
    before = C.overrides()
    r = cycle(dry_run=True, horizons=[20])
    assert C.overrides() == before
    assert all(not a.get("applied") for a in r["advanced"])


def test_the_cycle_reviews_before_it_advances(temp_db, monkeypatch):
    """An override that no longer holds is already affecting every
    prediction, so removing it outranks adding anything new."""
    order = []
    import selfimprove.loop as LP
    monkeypatch.setattr(LP, "review",
                        lambda cid, dry_run=False: order.append("review") or [])
    monkeypatch.setattr(LP, "advance",
                        lambda cid, dry_run=False, horizons=None:
                        order.append("advance") or [])
    LP.cycle(dry_run=True)
    assert order == ["review", "advance"]


def test_a_stale_override_is_rolled_back(temp_db, monkeypatch):
    import selfimprove.loop as LP
    C.apply(S.PILLAR_WEIGHTS, 20, CAND, proposal_id="p-old")
    monkeypatch.setattr(LP, "_evaluate_active", lambda g, h: {
        "group": g, "horizon_days": h, "verdict": V.REFUSE,
        "reason": "no longer clears the bar", "checks": [], "folds": []})
    out = LP.review("cyc", dry_run=False)
    assert any(r["action"] == "rolled_back" for r in out)
    assert C.active(S.PILLAR_WEIGHTS, 20) == C.defaults(S.PILLAR_WEIGHTS)


def test_the_loop_touches_nothing_outside_the_surface(temp_db):
    from selfimprove.loop import cycle
    r = cycle(dry_run=True, horizons=[20])
    for a in r["advanced"]:
        assert a["group"] in S.groups()
        for key in (a.get("candidate") or {}):
            assert S.is_tunable(a["group"], key)


# ── options outcomes: the half that was never graded ──────────────────────

def _options_brief(**kw):
    base = {
        "ticker": "AAA", "expiry": "2026-08-21", "spot": 300.0,
        "days_to_expiry": 45, "volatility_annualized_pct": 22.0,
        "volatility_basis": "REALIZED_30_BAR", "view": "BULLISH",
        "is_model_priced": True, "asset_class": "EQUITY",
        "candidates": [{
            "structure": "long_call",
            "legs": [{"kind": "call", "strike": 310.0, "qty": 1}],
            "net_cost": -950.0, "max_gain": None, "max_loss": -950.0,
            "breakevens": [319.5], "probability_of_profit": 0.42}]}
    base.update(kw)
    return base


def test_freezing_an_options_recommendation_is_idempotent(temp_db):
    from selfimprove.options_ledger import freeze
    b = _options_brief()
    assert freeze(b) == freeze(b), "the same recommendation froze twice"


def test_a_frozen_options_recommendation_is_immutable(temp_db):
    import sqlite3
    from data import prediction_ledger as PL
    from selfimprove.options_ledger import freeze
    freeze(_options_brief())
    conn = sqlite3.connect(PL._db())
    with pytest.raises(sqlite3.Error):
        conn.execute("UPDATE options_snapshots SET spot_at_call = 1.0")
    with pytest.raises(sqlite3.Error):
        conn.execute("DELETE FROM options_snapshots")
    conn.close()


def test_a_brief_with_no_candidate_is_not_frozen(temp_db):
    from selfimprove.options_ledger import freeze
    assert freeze(_options_brief(candidates=[])) is None


@pytest.mark.parametrize("settle,expect_profit", [
    (309.35, False),   # just below the 310 strike: expires worthless
    (400.00, True),    # deep in the money: 9000 intrinsic beats the 950 paid
])
def test_expiry_payoff_is_computed_from_the_settled_close(settle, expect_profit):
    from selfimprove.options_ledger import _payoff
    legs = [{"kind": "call", "strike": 310.0, "qty": 1}]
    payoff = _payoff("long_call", legs, settle) * 100.0
    profit = payoff - 950.0
    assert (profit > 0) is expect_profit


def test_the_contract_multiplier_is_applied(temp_db):
    """Legs are quoted per share and net_cost per contract. Missing the 100x
    would make every structure look like it moved a hundredth of what it did,
    and every long option would read as a loss."""
    from selfimprove.options_ledger import _payoff
    per_share = _payoff("long_call", [{"kind": "call", "strike": 310.0,
                                       "qty": 1}], 400.0)
    assert per_share == pytest.approx(90.0)
    assert per_share * 100.0 == pytest.approx(9000.0)


def test_a_short_structure_payoff_is_negative_when_it_loses():
    from selfimprove.options_ledger import _payoff
    short = _payoff("short_call", [{"kind": "call", "strike": 310.0,
                                    "qty": -1}], 400.0)
    assert short == pytest.approx(-90.0)


def test_the_options_report_separates_direction_from_volatility(temp_db):
    """They have different fixes: a desk right on direction and wrong on vol
    is mispricing every structure in a predictable direction, which is
    correctable. Reporting one number would hide which is which."""
    from selfimprove.options_ledger import report
    r = report()
    assert r["available"] is True
    if r.get("n"):
        assert "direction_claim" in r and "volatility_claim" in r


def test_an_ungraded_options_record_reports_honestly_rather_than_empty(temp_db):
    from selfimprove.options_ledger import report
    r = report()
    assert r["n"] == 0
    assert "has matured yet" in r["statement"]


# ── the limits of the method ──────────────────────────────────────────────

def test_long_horizons_are_named_out_of_reach_not_merely_short_of_data():
    """A 2-year horizon needs about 40 years of history for 20 non-overlapping
    windows. Reporting that as "3 of 20, keep collecting" implies a patience
    that will never be rewarded."""
    f = V.feasibility(504, dates=["2023-01-01", "2026-01-01"])
    assert f["state"] == "OUT_OF_REACH"
    assert "limit of the method" in f["statement"]


def test_more_sampling_does_not_move_the_independence_ceiling():
    """The SPAN ceiling is a fact about the calendar: thousands of calls
    inside three years still cannot contain twenty non-overlapping one-year
    windows. This is why the bar cannot be met by sampling harder."""
    import datetime as dt
    d0 = dt.date.fromisoformat("2023-01-01")
    sparse = [(d0 + dt.timedelta(days=30 * i)).isoformat() for i in range(36)]
    dense = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(1080)]
    assert V.feasibility(252, dates=sparse)["effective_n"] == \
           V.feasibility(252, dates=dense)["effective_n"]


def test_a_reachable_horizon_is_not_reported_as_out_of_reach():
    f = V.feasibility(20, dates=["2020-01-01", "2026-01-01"])
    assert f["state"] != "OUT_OF_REACH"


def test_years_required_scales_with_the_horizon():
    assert V.years_required(252) > V.years_required(20) > V.years_required(5)
    assert V.years_required(252) == pytest.approx(20.0, abs=0.5)


def test_the_bar_is_never_lowered_for_a_long_horizon():
    """The dishonest alternative to admitting a horizon is unreachable is to
    require fewer windows for it, which would tune multi-year behaviour on
    three overlapping observations."""
    import inspect
    src = inspect.getsource(V.evaluate) + inspect.getsource(V.evaluate_confidence)
    assert "MIN_EFFECTIVE_N" in src
    # No horizon-conditional relaxation of the threshold.
    assert "MIN_EFFECTIVE_N //" not in src
    assert "MIN_EFFECTIVE_N *" not in src


# ── the loop must not walk its own knobs ──────────────────────────────────

def test_a_knob_does_not_step_again_on_unchanged_evidence(temp_db):
    """A six-hourly cycle re-deriving the same conclusion from the same data
    takes another bounded step every time. Bounds cap the damage; twelve
    cycles a day still reach any bound inside a week."""
    import selfimprove.loop as LP
    from selfimprove import ledger as L
    C.apply(S.PILLAR_WEIGHTS, 20, CAND, proposal_id="p-live")
    L.record({"group": S.PILLAR_WEIGHTS, "horizon_days": 20, "current": CUR,
              "candidate": CAND, "verdict": V.PROMOTE, "reason": "ok",
              "effective_n": 52}, applied=True)
    may, why = LP._evidence_has_grown(S.PILLAR_WEIGHTS, 20, 52)
    assert may is False
    assert "same evidence" in why


def test_a_knob_may_step_again_once_new_windows_arrive(temp_db):
    import selfimprove.loop as LP
    from selfimprove import ledger as L
    C.apply(S.PILLAR_WEIGHTS, 20, CAND, proposal_id="p-live")
    L.record({"group": S.PILLAR_WEIGHTS, "horizon_days": 20, "current": CUR,
              "candidate": CAND, "verdict": V.PROMOTE, "reason": "ok",
              "effective_n": 52}, applied=True)
    may, _ = LP._evidence_has_grown(
        S.PILLAR_WEIGHTS, 20, 52 + LP.MIN_NEW_WINDOWS_TO_STEP_AGAIN)
    assert may is True


def test_a_promotion_the_config_does_not_reflect_cannot_strand_a_knob(temp_db):
    """Ledger and config can diverge. Gating on a promotion that is not
    actually applied leaves the knob reverted AND barred from re-earning the
    change -- permanently stuck."""
    import selfimprove.loop as LP
    from selfimprove import ledger as L
    L.record({"group": S.PILLAR_WEIGHTS, "horizon_days": 20, "current": CUR,
              "candidate": CAND, "verdict": V.PROMOTE, "reason": "ok",
              "effective_n": 52}, applied=True)
    # Config is at defaults: the recorded promotion is not in force.
    may, why = LP._evidence_has_grown(S.PILLAR_WEIGHTS, 20, 52)
    assert may is True
    assert "not reflected in the active config" in why


def test_rolling_back_marks_the_promotion_not_the_rollback_record(temp_db,
                                                                  monkeypatch):
    """Marking the new rollback row leaves the original looking live, so the
    cooldown keeps finding it and holds the knob forever."""
    import selfimprove.loop as LP
    from selfimprove import ledger as L
    C.apply(S.PILLAR_WEIGHTS, 20, CAND, proposal_id="p-old")
    original = L.record({"group": S.PILLAR_WEIGHTS, "horizon_days": 20,
                         "current": CUR, "candidate": CAND,
                         "verdict": V.PROMOTE, "reason": "ok",
                         "effective_n": 52}, applied=True)
    monkeypatch.setattr(LP, "_evaluate_active", lambda g, h: {
        "group": g, "horizon_days": h, "verdict": V.REFUSE,
        "reason": "stopped working", "checks": [], "folds": []})
    LP.review("cyc", dry_run=False)
    assert L.last_promotion(S.PILLAR_WEIGHTS, 20) is None, (
        "the original promotion is still listed as live after a rollback")
    rows = [r for r in L.history(S.PILLAR_WEIGHTS)
            if r["proposal_id"] == original]
    assert rows and rows[0]["rolled_back_at"] is not None


def test_re_testing_a_live_config_ignores_the_step_limit():
    """max_step governs how fast the loop may move a knob, not which positions
    may exist. A knob two legitimate steps from default is two max_steps away
    from it, and re-testing with the step check on rolls back a position that
    was reached correctly."""
    far = {"technical": 0.30, "algo": 0.30, "fundamentals": 0.40}
    strict = V.evaluate(S.PILLAR_WEIGHTS, CUR, far, 20, graphs=_graphs(400))
    assert strict["checks"][0]["check"] == "surface"
    assert not strict["checks"][0]["passed"], "max_step should bite here"

    lenient = V.evaluate(S.PILLAR_WEIGHTS, CUR, far, 20,
                         graphs=_graphs(400), check_step=False)
    assert lenient["checks"][0]["passed"], (
        "re-testing a live config must not fail on the speed limit")


def test_re_testing_still_enforces_bounds():
    """Relaxing the step check must not relax the bounds with it."""
    out = {"technical": 0.05, "algo": 0.05, "fundamentals": 0.90}
    r = V.evaluate(S.PILLAR_WEIGHTS, CUR, out, 20, graphs=_graphs(400),
                   check_step=False)
    assert not r["checks"][0]["passed"]
    assert "bounds" in r["checks"][0]["detail"]


def test_cooldown_is_reported_separately_from_a_thin_evidence_refusal(temp_db):
    """Both mention independent windows. Lumping them together reports a knob
    that was just promoted as though its evidence were too thin."""
    from selfimprove.loop import _statement
    advanced = [
        {"verdict": "COOLDOWN", "reason": "only 0 new independent windows"},
        {"verdict": V.REFUSE, "reason": "3 independent 252-day windows, need 20"},
    ]
    text = _statement(advanced, [], dry_run=False)
    assert "1 held in cooldown" in text
    assert "refused 1 for too few independent windows" in text


# ── the confidence label must carry its record ────────────────────────────

def test_a_level_with_no_measured_record_says_nothing(monkeypatch):
    """A badge with no history behind it must look like one. Rendering a
    reassuring default would replace an unfounded number with another."""
    from selfimprove import reliability as R
    monkeypatch.setattr(R, "realized", lambda lvl, h: None)
    monkeypatch.setattr(R, "calibrated", lambda lvl, h: None)
    assert R.describe("HIGH", 20) is None


def test_a_thin_sample_is_not_quoted(monkeypatch):
    """A realised rate over a handful of calls is noise with a decimal point."""
    from selfimprove import reliability as R
    monkeypatch.setattr(
        "data.prediction_ledger.calibration_report",
        lambda horizon, source="all": {"confidence_reliability": [
            {"level": "MEDIUM", "n": R.MIN_N_TO_QUOTE - 1,
             "realized_win_rate": 1.0, "predicted_win_prob": 0.9,
             "calibration_gap": 0.1}]})
    assert R.realized("MEDIUM", 20) is None


def test_an_untouched_default_is_not_dressed_up_as_calibrated(temp_db):
    """Reporting the shipped constant as a validated figure would be the same
    overclaim this module exists to remove."""
    from selfimprove import reliability as R
    assert R.calibrated("MEDIUM", 20) is None
    C.apply(S.CONFIDENCE_MAP, 20,
            {"LOW": 0.617, "MEDIUM": 0.777, "HIGH": 0.95})
    assert R.calibrated("MEDIUM", 20) == pytest.approx(0.777)
    assert R.calibrated("HIGH", 20) is None, "HIGH was never moved"


def test_annotate_leaves_the_dict_untouched_when_silent(monkeypatch):
    from selfimprove import reliability as R
    monkeypatch.setattr(R, "describe", lambda lvl, h: None)
    original = {"decision_confidence": "MEDIUM", "summary": "x"}
    assert R.annotate(original, 20) == original


def test_annotate_does_not_mutate_its_input(monkeypatch):
    from selfimprove import reliability as R
    monkeypatch.setattr(R, "describe",
                        lambda lvl, h: {"statement": "won 53% of 90."})
    original = {"decision_confidence": "MEDIUM", "summary": "x"}
    out = R.annotate(original, 20)
    assert "track_record" not in original, "the caller's dict was mutated"
    assert out["track_record"]["statement"] == "won 53% of 90."


def test_the_gap_is_only_called_out_when_it_is_material(monkeypatch):
    from selfimprove import reliability as R
    monkeypatch.setattr(R, "calibrated", lambda lvl, h: None)
    monkeypatch.setattr(R, "realized", lambda lvl, h: {
        "n": 100, "realized_win_rate": 0.60, "stated_win_prob": 0.61,
        "gap": 0.01})
    d = R.describe("MEDIUM", 20)
    assert "gap of" not in d["statement"], "a 1-point gap was called out"

    monkeypatch.setattr(R, "realized", lambda lvl, h: {
        "n": 100, "realized_win_rate": 0.53, "stated_win_prob": 0.88,
        "gap": 0.34})
    assert "gap of 34 points" in R.describe("MEDIUM", 20)["statement"]


def test_the_confidence_map_is_now_read_outside_the_loop():
    """The regression guard for the bug this module fixes: the loop promoted a
    calibrated confidence map, stored it, and nothing consulted it — a knob
    that reported as live while changing nothing.

    Asserted against the imported module's own file rather than a grep from the
    working directory, so the test does not depend on where pytest was invoked
    or on an external binary."""
    import pathlib
    import decision.engine as E
    src = pathlib.Path(E.__file__).read_text()
    assert "selfimprove.reliability" in src, (
        "decision/engine.py no longer consults the confidence track record")


def test_the_engine_survives_the_reliability_lookup_failing(monkeypatch):
    """The record is worth having, never at the cost of the brief."""
    from selfimprove import reliability as R

    def _boom(*a, **k):
        raise RuntimeError("ledger unreachable")

    monkeypatch.setattr(R, "describe", _boom)
    out = R.annotate({"decision_confidence": "MEDIUM", "summary": "x"}, 20)
    assert out["decision_confidence"] == "MEDIUM"


def test_apply_mode_is_observable(monkeypatch):
    """A loop whose arming cannot be observed is one nobody can tell is
    working. It must read the same variable data.maintenance reads, so it
    reports the running process rather than a separate opinion about it."""
    from selfimprove.loop import apply_mode
    monkeypatch.delenv("SELFIMPROVE_APPLY", raising=False)
    assert apply_mode()["armed"] is False
    assert "DRY" in apply_mode()["statement"]
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv("SELFIMPROVE_APPLY", truthy)
        assert apply_mode()["armed"] is True, truthy
    monkeypatch.setenv("SELFIMPROVE_APPLY", "0")
    assert apply_mode()["armed"] is False


def test_apply_mode_agrees_with_what_the_scheduler_actually_does(monkeypatch):
    """The two must not drift apart: a status page saying ARMED while the job
    runs dry is worse than no status page."""
    from selfimprove.loop import apply_mode
    from data import maintenance as m
    seen = {}
    import selfimprove.loop as LP
    monkeypatch.setattr(LP, "cycle", lambda dry_run=False, horizons=None: (
        seen.update(dry_run=dry_run) or {
            "cycle_id": "x", "dry_run": dry_run, "n_proposed": 0,
            "n_promoted": 0, "n_refused": 0, "n_rolled_back": 0,
            "statement": ""}))
    for value, expect_armed in (("1", True), ("", False)):
        monkeypatch.setenv("SELFIMPROVE_APPLY", value)
        m.self_improve()
        assert apply_mode()["armed"] is expect_armed
        assert seen["dry_run"] is (not expect_armed)


# ── carrying learned parameters to a deployment that cannot learn ──────────

def _as_secondary(monkeypatch):
    """Simulate a deployment whose own snapshots are quarantined."""
    monkeypatch.setattr("data.prediction_ledger.is_canonical_ledger",
                        lambda: False)


def test_a_secondary_deployment_serves_the_seed(temp_db, monkeypatch):
    _as_secondary(monkeypatch)
    """A secondary ledger quarantines its own snapshots, so it can never learn.
    Without the seed layer it would serve shipped defaults forever while the
    canonical machine held validated better ones."""
    from selfimprove import seed
    monkeypatch.setattr(seed, "_cache", None)
    monkeypatch.setattr(seed, "load", lambda: {
        S.PILLAR_WEIGHTS: {"20": {"technical": 0.4, "algo": 0.35,
                                  "fundamentals": 0.25}}})
    assert C.active(S.PILLAR_WEIGHTS, 20)["fundamentals"] == pytest.approx(0.25)
    assert C.active(S.PILLAR_WEIGHTS, 5) == C.defaults(S.PILLAR_WEIGHTS), \
        "the seed must stay scoped to the horizon it was learned at"


def test_a_local_override_beats_the_seed(temp_db, monkeypatch):
    _as_secondary(monkeypatch)
    """Otherwise exporting a seed and reading it back would be circular, and a
    deployment that learned its own value would be overwritten by an older one."""
    from selfimprove import seed
    monkeypatch.setattr(seed, "_cache", None)
    monkeypatch.setattr(seed, "load", lambda: {
        S.PILLAR_WEIGHTS: {"20": {"technical": 0.4, "algo": 0.35,
                                  "fundamentals": 0.25}}})
    C.apply(S.PILLAR_WEIGHTS, 20,
            {"technical": 0.40, "algo": 0.30, "fundamentals": 0.30})
    assert C.active(S.PILLAR_WEIGHTS, 20)["algo"] == pytest.approx(0.30)


def test_an_invalid_seed_is_ignored_rather_than_scored(temp_db, monkeypatch):
    _as_secondary(monkeypatch)
    """The seed is a committed file, so it can be hand-edited. One that breaks
    an invariant must not reach a score; staying on defaults is the safe
    failure."""
    from selfimprove import seed
    monkeypatch.setattr(seed, "_cache", None)
    monkeypatch.setattr(seed, "load", lambda: {
        S.PILLAR_WEIGHTS: {"20": {"technical": 0.5, "algo": 0.5,
                                  "fundamentals": 0.5}}})       # sums to 1.5
    assert seed.for_group(S.PILLAR_WEIGHTS, 20) == {}
    assert C.active(S.PILLAR_WEIGHTS, 20) == C.defaults(S.PILLAR_WEIGHTS)


def test_a_seed_key_outside_the_surface_is_dropped(temp_db, monkeypatch):
    _as_secondary(monkeypatch)
    from selfimprove import seed
    monkeypatch.setattr(seed, "_cache", None)
    monkeypatch.setattr(seed, "load", lambda: {
        S.PILLAR_WEIGHTS: {"20": {"technical": 0.4, "algo": 0.35,
                                  "fundamentals": 0.25,
                                  "risk_veto_threshold": 0.9}}})
    assert "risk_veto_threshold" not in seed.for_group(S.PILLAR_WEIGHTS, 20)


def test_a_missing_seed_is_not_an_error(temp_db, monkeypatch):
    _as_secondary(monkeypatch)
    from selfimprove import seed
    monkeypatch.setattr(seed, "_cache", None)
    monkeypatch.setattr(seed, "SEED_PATH",
                        pathlib_Path_that_does_not_exist())
    assert seed.load() == {}
    assert C.active(S.PILLAR_WEIGHTS, 20) == C.defaults(S.PILLAR_WEIGHTS)


def pathlib_Path_that_does_not_exist():
    import pathlib
    return pathlib.Path("/nonexistent") / "no-such-seed.json"


def test_only_the_canonical_ledger_may_export_a_seed(monkeypatch):
    """A secondary deployment exporting its empty state would overwrite the
    real learned parameters with nothing."""
    from selfimprove import seed
    monkeypatch.setattr("data.prediction_ledger.is_canonical_ledger",
                        lambda: False)
    monkeypatch.setattr("data.prediction_ledger.ledger_role",
                        lambda: "secondary")
    r = seed.export()
    assert r["written"] is False
    assert "canonical" in r["reason"]


def test_status_states_whether_this_deployment_can_learn():
    """A loop on a secondary deployment looks identical to one that is
    learning, and the difference matters entirely."""
    from selfimprove.loop import _ledger_role
    r = _ledger_role()
    assert "can_learn" in r and r["statement"]


def test_the_canonical_ledger_ignores_its_own_seed(temp_db, monkeypatch):
    """Reading its own export as a baseline would make every comparison
    circular: review would re-test a learned value against itself and find no
    effect, and the cooldown would read a seeded value as a promotion already
    in force."""
    from selfimprove import seed
    monkeypatch.setattr("data.prediction_ledger.is_canonical_ledger",
                        lambda: True)
    monkeypatch.setattr(seed, "_cache", None)
    monkeypatch.setattr(seed, "load", lambda: {
        S.PILLAR_WEIGHTS: {"20": {"technical": 0.4, "algo": 0.35,
                                  "fundamentals": 0.25}}})
    assert seed.for_group(S.PILLAR_WEIGHTS, 20) == {}
    assert C.active(S.PILLAR_WEIGHTS, 20) == C.defaults(S.PILLAR_WEIGHTS)
    assert seed.describe()["seeded"] is False
    assert seed.describe()["seed_present"] is True


def test_an_unknown_ledger_role_ignores_the_seed(monkeypatch):
    """Ignoring the seed cannot cause a deployment to score on numbers nobody
    can trace; applying it under an unknown role could."""
    from selfimprove import seed
    def _boom():
        raise RuntimeError("role unavailable")
    monkeypatch.setattr("data.prediction_ledger.is_canonical_ledger", _boom)
    assert seed.applies_here() is False


# ── the desk decides at horizons the loop does not tune ───────────────────

def test_a_desk_horizon_resolves_to_the_nearest_tuned_one():
    """The loop tunes at the ledger's evaluation horizons; the desk decides at
    45, 91 or 126 days by volatility regime. Exact-match lookup found nothing
    for almost every real decision, so the learned parameters were served and
    consulted by nothing — the third time that pattern appeared in this
    package's own wiring."""
    from selfimprove.config import resolve_horizon
    assert resolve_horizon(91)[0] == 60
    assert resolve_horizon(45)[0] == 60
    assert resolve_horizon(126)[0] == 126


def test_an_exact_horizon_is_never_rewritten():
    from selfimprove.config import TUNED_HORIZONS, resolve_horizon
    for h in TUNED_HORIZONS:
        assert resolve_horizon(h)[0] == h


def test_a_horizon_too_far_from_any_tuned_one_gets_no_override():
    """Borrowing weights learned on a different relationship to forward return
    is the thing horizon scoping exists to prevent, so beyond the tolerance no
    override applies at all."""
    from selfimprove.config import resolve_horizon
    # 12d: nearest tuned is 5d, 58% away — beyond tolerance.
    assert resolve_horizon(12)[0] is None
    assert "no tuned horizon within" in resolve_horizon(12)[1]
    # 1d and 2d are far outside every tuned horizon.
    assert resolve_horizon(1)[0] is None
    assert resolve_horizon(2)[0] is None


def test_the_tolerance_is_proportional_not_absolute():
    """The same absolute gap means very different things at different horizons.
    52 days from 252 is close; 7 days from 5 is not."""
    from selfimprove.config import resolve_horizon
    assert resolve_horizon(200)[0] == 252, "52d away, but only 26% of 200"
    assert resolve_horizon(12)[0] is None, "7d away, but 58% of 12"


def test_a_missing_horizon_applies_no_learned_parameters():
    from selfimprove.config import resolve_horizon
    assert resolve_horizon(None)[0] is None


def test_the_score_discloses_the_horizon_its_weights_were_learned_at(temp_db):
    """A reader comparing two decisions needs to know when one was scored with
    parameters learned at a different horizon."""
    from backtest.pillars import compute_pillar_scores as cps
    args = dict(ticker="AAA", indicators={}, signal_summary={},
                algo_signals={}, fundamentals={})
    C.apply(S.PILLAR_WEIGHTS, 60,
            {"technical": 0.40, "algo": 0.35, "fundamentals": 0.25})
    src = cps(**args, horizon_days=91)["weight_source"]
    assert "60d" in src and "asked 91d" in src
    assert "60d" in cps(**args, horizon_days=60)["weight_source"]
    assert "asked" not in cps(**args, horizon_days=60)["weight_source"]


def test_the_recommendation_scores_pillars_at_its_own_horizon():
    """Regression guard: the pillars were scored before the horizon existed, so
    every horizon-scoped weight was unreachable from the real pipeline."""
    import inspect
    import agents.recommendation as R
    src = inspect.getsource(R)
    pillars_at = src.index("compute_pillar_scores(")
    horizon_at = src.index("time_horizon_days = {")
    assert horizon_at < pillars_at, (
        "the horizon must be derived before the pillars are scored")
    assert "horizon_days=time_horizon_days" in src, (
        "the recommendation no longer passes its horizon to the pillars")
