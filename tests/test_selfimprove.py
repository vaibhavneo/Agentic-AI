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
