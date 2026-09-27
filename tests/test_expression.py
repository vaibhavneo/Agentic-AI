"""
Equity against options on common terms.

The arithmetic here decides a real choice, so the tests are mostly about the
ways it could mislead: a normalisation that flatters one instrument, a sign that
turns a kept credit into a paid debit, a stop so tight that the leverage it
implies could never be held.
"""
from __future__ import annotations

import pytest

from decision.expression import (MARKET, MODEL, REFERENCE_RISK_CAPITAL,
                                 _stop_in_daily_sigma, compare)


def _credit_condor():
    return {
        "structure": "iron_condor", "label": "Sell an iron condor",
        "legs": [{"kind": "put", "strike": 20.0, "qty": 1},
                 {"kind": "put", "strike": 35.0, "qty": -1},
                 {"kind": "call", "strike": 60.0, "qty": -1},
                 {"kind": "call", "strike": 70.0, "qty": 1}],
        "legs_text": "…", "net_cost": -189.41, "max_gain": 189.41,
        "max_loss": -1310.59, "breakevens": [33.11, 61.89],
        "greeks": {"theta": 0.049}, "probability_of_profit": 0.73,
        "probability_basis": "…",
    }


def _debit_call():
    return {
        "structure": "long_call", "label": "Buy a call",
        "legs": [{"kind": "call", "strike": 50.0, "qty": 1}],
        "legs_text": "…", "net_cost": 500.0, "max_gain": None,
        "max_gain_unbounded": True, "max_loss": -500.0, "breakevens": [55.0],
        "greeks": {"theta": -0.08},
    }


def _section(cands, vol_basis="IMPLIED_BY_CHAIN", vol=79.0):
    return {"candidates": cands, "volatility_basis": vol_basis,
            "volatility_annualized_pct": vol, "contract_multiplier": 100.0,
            "expiry": "2026-11-20"}


# ── the normalisation ─────────────────────────────────────────────────────

def test_every_row_risks_the_same_capital():
    """One share against one contract compares nothing: a contract controls a
    hundred shares. Equal capital at risk is what a reader actually decides."""
    r = compare(_section([_credit_condor(), _debit_call()]),
                spot=45.0, invalidation=40.0, target=60.0)
    assert r["status"] == "OK"
    assert r["normalised_on"] == "EQUAL_CAPITAL_AT_RISK"
    for row in r["rows"]:
        if row["status"] == "OK":
            assert row["capital_at_risk"] == pytest.approx(REFERENCE_RISK_CAPITAL)
            assert row["max_loss"] == pytest.approx(-REFERENCE_RISK_CAPITAL)


def test_leverage_shows_up_as_notional_not_as_hidden_size():
    """The point of the option is leverage, so it must be visible rather than
    smuggled into the return."""
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=40.0,
                target=60.0)
    eq = r["rows"][0]
    assert eq["notional_exposure"] > eq["capital_at_risk"]
    assert eq["leverage_x"] > 1.0


# ── the sign trap ─────────────────────────────────────────────────────────

def test_a_credit_structure_inside_its_band_keeps_the_whole_credit():
    """net_cost is NEGATIVE for a credit (-189.41 means 189.41 received), so
    P&L subtracts it. Adding it reported a 130% loss on a structure whose
    maximum loss is contractually 100%."""
    r = compare(_section([_credit_condor()]), spot=45.0, invalidation=40.0,
                target=50.0)          # 50 is inside the 35-60 band
    row = next(x for x in r["rows"] if x["instrument"] == "iron_condor")
    # Expiring worthless inside the band returns exactly the credit, scaled.
    assert row["gain_at_target"] == pytest.approx(row["max_gain"], rel=1e-6)
    assert row["gain_at_target"] > 0


def test_a_loss_beyond_the_contractual_maximum_is_refused():
    """A contractual max loss cannot be exceeded, so arithmetic that says
    otherwise is a bug. Clamping silently would hide the next one."""
    broken = _credit_condor()
    broken["max_loss"] = -1.0        # absurdly small against the real payoff
    r = compare(_section([broken]), spot=45.0, invalidation=40.0, target=100.0)
    row = next(x for x in r["rows"] if x["instrument"] == "iron_condor")
    assert row["status"] == "INCONSISTENT"
    assert "exceeds the contractual maximum" in row["reason"]


def test_a_debit_structure_below_its_strike_loses_the_premium():
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=40.0,
                target=46.0)          # below the 50 strike: expires worthless
    row = next(x for x in r["rows"] if x["instrument"] == "long_call")
    assert row["gain_at_target"] == pytest.approx(-REFERENCE_RISK_CAPITAL,
                                                 rel=1e-6)


# ── the stop that cannot be held ──────────────────────────────────────────

def test_a_stop_inside_one_daily_move_is_flagged():
    """Equal capital at risk turns a tight stop into enormous leverage, and that
    leverage is only real if noise does not take the stop out first."""
    sigmas = _stop_in_daily_sigma(45.48, 44.38, 79.0)
    assert sigmas is not None and sigmas < 1.0
    r = compare(_section([_debit_call()]), spot=45.48, invalidation=44.38,
                target=60.0)
    eq = r["rows"][0]
    assert eq["stop_survivable"] is False
    assert "INSIDE ONE DAILY MOVE" in eq["caveats"][0]


def test_an_unsurvivable_stop_cannot_win_the_comparison():
    """A 2.4% stop on a 79%-vol name computes 1320% return on risk. Letting that
    top the table would recommend a position nobody could hold."""
    r = compare(_section([_debit_call()]), spot=45.48, invalidation=44.38,
                target=60.0)
    eq = r["rows"][0]
    assert eq["return_on_risk_at_target_pct"] > 1000, "the arithmetic still runs"
    assert r["highest_return_at_target"] != "EQUITY"
    assert "not achievable" in eq["return_on_risk_at_target_pct_note"]


def test_a_wide_stop_is_survivable_and_may_win():
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=30.0,
                target=60.0)
    assert r["rows"][0]["stop_survivable"] is True


def test_sigma_is_none_when_no_volatility_is_known():
    assert _stop_in_daily_sigma(45.0, 40.0, None) is None
    assert _stop_in_daily_sigma(45.0, 40.0, 0.0) is None


# ── provenance ────────────────────────────────────────────────────────────

def test_market_priced_options_are_labelled_market():
    r = compare(_section([_debit_call()], vol_basis="IMPLIED_BY_CHAIN"),
                spot=45.0, invalidation=40.0, target=60.0)
    assert r["pricing_source"] == MARKET
    row = next(x for x in r["rows"] if x["instrument"] == "long_call")
    assert "implied volatility" in row["pricing_note"]


def test_model_priced_options_say_the_market_may_charge_otherwise():
    r = compare(_section([_debit_call()], vol_basis="REALIZED_30_BAR"),
                spot=45.0, invalidation=40.0, target=60.0)
    assert r["pricing_source"] == MODEL
    assert "may differ materially" in r["what_this_does_not_say"]


def test_it_never_claims_market_pricing_improves_the_forecast():
    """Implied vol makes the PREMIUM right, not the direction predictable, and
    nothing in this system has shown a directional edge."""
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=40.0,
                target=60.0)
    txt = r["what_this_does_not_say"]
    assert "not the direction predictable" in txt
    assert "forecasts the target" in txt


# ── refusals ──────────────────────────────────────────────────────────────

def test_a_missing_reference_level_refuses_rather_than_inventing_one():
    """An invented target would make every row a guess wearing the same
    formatting as a measurement."""
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=40.0,
                target=None)
    assert r["status"] == "UNAVAILABLE"
    assert "target" in r["reason"]


def test_an_invalidation_above_the_price_is_not_comparable():
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=50.0,
                target=60.0)
    assert r["rows"][0]["status"] == "NOT_COMPARABLE"
    assert "not below" in r["rows"][0]["reason"]


def test_no_spot_is_refused():
    r = compare(_section([_debit_call()]), spot=None, invalidation=40.0,
                target=60.0)
    assert r["status"] == "UNAVAILABLE"


def test_a_structure_with_no_bounded_loss_is_not_comparable():
    naked = _debit_call()
    naked["max_loss"] = None
    r = compare(_section([naked]), spot=45.0, invalidation=40.0, target=60.0)
    row = next(x for x in r["rows"] if x["instrument"] == "long_call")
    assert row["status"] == "NOT_COMPARABLE"


# ── asymmetries the table must state ──────────────────────────────────────

def test_the_equity_stop_is_declared_non_contractual():
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=30.0,
                target=60.0)
    eq = r["rows"][0]
    assert eq["max_loss_is_contractual"] is False
    assert any("gap" in c for c in eq["caveats"])


def test_option_max_loss_is_declared_contractual():
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=30.0,
                target=60.0)
    row = next(x for x in r["rows"] if x["instrument"] == "long_call")
    assert row["max_loss_is_contractual"] is True


def test_expiry_is_stated_on_every_option_row_and_absent_on_equity():
    """A thesis right on the wrong schedule loses the premium and costs the
    equity holder nothing."""
    r = compare(_section([_debit_call()]), spot=45.0, invalidation=30.0,
                target=60.0)
    assert r["rows"][0]["expires"] is None
    row = next(x for x in r["rows"] if x["instrument"] == "long_call")
    assert row["expires"] == "2026-11-20"
    assert any("expires" in c for c in row["caveats"])
