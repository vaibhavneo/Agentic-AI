"""
The pricing agent, the option chain, and the retirement of social.

The through-line: the desk priced options from REALIZED volatility while the
market charges IMPLIED, and it gave 5 composite points to a pillar that measured
+0.016 correlation with forward return. Both are now fixed, and these tests
guard the properties that make the fixes real rather than cosmetic.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backtest.pillars import (MODIFIER_PILLARS, RETIRED_MODIFIERS,
                              compute_pillar_scores)


# ── social: scored, not counted ───────────────────────────────────────────

def test_social_no_longer_tilts_the_composite():
    """It measured +0.016 / -0.026 correlation with forward return at 5 / 20
    days, on samples of 250 and 14, with nothing at 60. Five composite points
    for that is five points of noise."""
    args = dict(ticker="AAA", indicators={}, signal_summary={},
                algo_signals={}, fundamentals={})
    bullish = compute_pillar_scores(
        **args, reddit={"sentiment_score": 100, "total": 500},
        stocktwits={"sentiment_ratio": 100, "total": 500})
    bearish = compute_pillar_scores(
        **args, reddit={"sentiment_score": -100, "total": 500},
        stocktwits={"sentiment_ratio": 0, "total": 500})
    assert bullish["composite"] == bearish["composite"]


def test_social_is_still_scored_so_it_can_earn_its_way_back():
    """A pillar that stops being computed stops generating attributable
    observations, so its retirement would be permanent regardless of later
    evidence. Scored-but-not-counted keeps the loop able to change its mind."""
    args = dict(ticker="AAA", indicators={}, signal_summary={},
                algo_signals={}, fundamentals={})
    r = compute_pillar_scores(
        **args, reddit={"sentiment_score": 100, "total": 500},
        stocktwits={"sentiment_ratio": 100, "total": 500})
    assert "social" in r["pillars"]
    assert r["pillars"]["social"]["score"] != 50.0, "social must still compute"


def test_the_retirement_is_declared_not_implicit():
    """A reader seeing a pillar with a score must be able to tell it counted for
    nothing, rather than deducing it from the arithmetic."""
    args = dict(ticker="AAA", indicators={}, signal_summary={},
                algo_signals={}, fundamentals={})
    r = compute_pillar_scores(**args)
    assert r["modifier_pillars"] == list(MODIFIER_PILLARS)
    assert r["retired_modifiers"] == list(RETIRED_MODIFIERS)
    assert "social" in r["retired_modifiers"]
    assert "social" not in r["modifier_pillars"]


def test_research_still_tilts_the_composite():
    """Retiring one modifier must not silently retire the other: research
    measured +0.121 / +0.189 correlation, an order above social."""
    assert "research" in MODIFIER_PILLARS


# ── the option chain kind ─────────────────────────────────────────────────

def test_option_chain_is_a_registered_kind():
    from financial_data.schemas import KINDS
    assert "option_chain" in KINDS


def test_a_chain_is_never_point_in_time_capable():
    """A chain is a live snapshot and no free vendor serves a historical one.
    Claiming otherwise would let a backtest read today's implied vol into a
    past decision."""
    from financial_data.gateway import list_providers
    provs = list_providers("option_chain")
    assert provs, "no provider serves option_chain"
    for p in provs:
        assert "option_chain" not in (p.get("pit_capable") or [])


def test_the_atm_solver_uses_contracts_near_the_money():
    """Averaging the whole chain produces a volatility that describes no
    contract anybody would trade, because the wings carry their own skew."""
    from financial_data.providers.yfinance_chain import _atm_iv
    # Wings at 10 and 200 carry their own skew; the money is near 50.
    calls = [{"strike": 10.0, "implied_volatility": 2.00, "open_interest": 10,
              "in_the_money": True},
             {"strike": 30.0, "implied_volatility": 1.20, "open_interest": 10,
              "in_the_money": True},
             {"strike": 48.0, "implied_volatility": 0.50, "open_interest": 10,
              "in_the_money": True},
             {"strike": 52.0, "implied_volatility": 0.52, "open_interest": 10,
              "in_the_money": False},
             {"strike": 90.0, "implied_volatility": 1.30, "open_interest": 10,
              "in_the_money": False},
             {"strike": 200.0, "implied_volatility": 1.90, "open_interest": 10,
              "in_the_money": False}]
    iv = _atm_iv(calls, [])
    assert 0.45 < iv < 0.60, f"wing skew leaked into the ATM figure: {iv}"


def test_the_atm_band_is_proportional_not_a_fixed_count():
    """A fixed nearest-N is the whole chain on a thin name: four live contracts
    with a 200-strike wing returned 1.23 where the money was near 0.51."""
    from financial_data.providers.yfinance_chain import _atm_iv
    thin = [{"strike": 10.0, "implied_volatility": 2.00, "open_interest": 10,
             "in_the_money": True},
            {"strike": 49.0, "implied_volatility": 0.50, "open_interest": 10,
             "in_the_money": True},
            {"strike": 51.0, "implied_volatility": 0.52, "open_interest": 10,
             "in_the_money": False},
            {"strike": 200.0, "implied_volatility": 1.90, "open_interest": 10,
             "in_the_money": False}]
    iv = _atm_iv(thin, [])
    assert 0.45 < iv < 0.60, f"the wings leaked in on a thin chain: {iv}"


def test_a_contract_with_no_open_interest_is_ignored():
    """An implied vol solved from a stale or one-sided quote is arithmetic on
    nothing."""
    from financial_data.providers.yfinance_chain import _atm_iv
    assert _atm_iv([{"strike": 50.0, "implied_volatility": 9.9,
                     "open_interest": 0, "in_the_money": True}], []) is None


def test_an_empty_chain_yields_none_not_zero():
    from financial_data.providers.yfinance_chain import _atm_iv
    assert _atm_iv([], []) is None


# ── the expiry fix ────────────────────────────────────────────────────────

def test_a_listed_expiry_is_preferred_over_a_computed_friday(monkeypatch):
    """expiry_date() snaps to Friday, which produced 2026-11-13 for IONQ — a
    date IONQ does not list. Pricing it quotes a contract nobody can trade."""
    import mas.options_brief as OB
    monkeypatch.setattr(
        "financial_data.providers.yfinance_chain.expirations",
        lambda sym: ["2026-11-06", "2026-11-20", "2026-12-18"])
    import datetime as dt
    got = OB.listed_expiry("IONQ", 45, today=dt.date(2026, 9, 26))
    assert got in ("2026-11-06", "2026-11-20")
    assert got != "2026-11-13"


def test_an_unreachable_chain_falls_back_rather_than_failing(monkeypatch):
    """Being unable to read the chain must cost the precision, not the answer."""
    import mas.options_brief as OB

    def _boom(sym):
        raise RuntimeError("chain unreachable")

    monkeypatch.setattr(
        "financial_data.providers.yfinance_chain.expirations", _boom)
    assert OB.listed_expiry("IONQ", 45) is None


def test_the_nearest_listed_expiry_is_chosen(monkeypatch):
    import datetime as dt
    import mas.options_brief as OB
    monkeypatch.setattr(
        "financial_data.providers.yfinance_chain.expirations",
        lambda sym: ["2026-10-02", "2026-11-20", "2027-01-15"])
    # 45 days from 2026-09-26 is 2026-11-10; 11-20 is nearest.
    assert OB.listed_expiry("X", 45, today=dt.date(2026, 9, 26)) == "2026-11-20"


# ── the pricing agent ─────────────────────────────────────────────────────

def _frame(n=300, price=45.0):
    idx = pd.bdate_range("2025-08-01", periods=n)
    return pd.DataFrame({"Close": [price] * n, "Open": [price] * n,
                         "High": [price * 1.01] * n, "Low": [price * 0.99] * n,
                         "Volume": [1_000_000] * n}, index=idx)


def _req(symbol="AAA", capability="price_discovery"):
    from mas.contract import AgentRequest
    return AgentRequest(symbol=symbol, capability=capability,
                        asset_class="EQUITY", params={})


def test_the_pricing_agent_is_keyless():
    from mas.agents.pricing import available
    assert available()["available"] is True


def test_it_serves_only_its_own_capability():
    from mas.agents.pricing import run
    r = run(_req(capability="option_structures"))
    assert r.status != "OK"
    assert "price_discovery" in r.reason


def test_the_volatility_gap_states_its_direction(monkeypatch):
    """The same number means opposite things by sign, so the reading is stated
    rather than left to the reader."""
    import mas.agents.pricing as PR
    monkeypatch.setattr(PR, "_bars", lambda s, period="1y": _frame())
    monkeypatch.setattr(PR, "_realized_vol_pct", lambda *a, **k: 40.0)
    monkeypatch.setattr(PR, "_implied_vol_pct", lambda s: {
        "available": True, "implied_pct": 55.0, "expiration": "2026-11-20",
        "n_contracts": 50})
    monkeypatch.setattr("mas.realtime.consensus", lambda *a, **k: {
        "price": 45.0, "confirmation": "CROSS_VENDOR", "usable": True,
        "n_sources": 2, "spread_pct": 0.0, "statement": "ok"})
    d = PR.run(_req()).data
    gap = d["volatility"]["gap"]
    assert gap["gap_points"] == pytest.approx(15.0)
    assert "MORE movement" in gap["reading"]


def test_horizon_bands_use_implied_vol_when_the_market_gave_one(monkeypatch):
    """A forward-looking band built on a backward-looking number is the same
    mistake the option engine was making."""
    import mas.agents.pricing as PR
    monkeypatch.setattr(PR, "_bars", lambda s, period="1y": _frame())
    monkeypatch.setattr(PR, "_realized_vol_pct", lambda *a, **k: 40.0)
    monkeypatch.setattr(PR, "_implied_vol_pct", lambda s: {
        "available": True, "implied_pct": 80.0, "expiration": "x",
        "n_contracts": 10})
    monkeypatch.setattr("mas.realtime.consensus", lambda *a, **k: {
        "price": 45.0, "confirmation": "CROSS_VENDOR", "usable": True,
        "n_sources": 2, "spread_pct": 0.0, "statement": "ok"})
    d = PR.run(_req()).data
    assert d["band_volatility_basis"] == "IMPLIED_BY_CHAIN"


def test_it_falls_back_to_realized_when_no_chain_exists(monkeypatch):
    import mas.agents.pricing as PR
    monkeypatch.setattr(PR, "_bars", lambda s, period="1y": _frame())
    monkeypatch.setattr(PR, "_realized_vol_pct", lambda *a, **k: 40.0)
    monkeypatch.setattr(PR, "_implied_vol_pct", lambda s: {
        "available": False, "reason": "no listed expirations"})
    monkeypatch.setattr("mas.realtime.consensus", lambda *a, **k: {
        "price": 45.0, "confirmation": "SINGLE", "usable": True,
        "n_sources": 1, "spread_pct": None, "statement": "ok"})
    d = PR.run(_req()).data
    assert d["band_volatility_basis"] == "REALIZED_30_BAR"
    assert d["volatility"]["gap"] is None
    assert d["volatility"]["implied_absent_reason"]


def test_it_states_no_forecast(monkeypatch):
    """Nothing in this system has demonstrated a forward edge, so an agent that
    quoted a probability would be claiming one."""
    import mas.agents.pricing as PR
    monkeypatch.setattr(PR, "_bars", lambda s, period="1y": _frame())
    monkeypatch.setattr(PR, "_realized_vol_pct", lambda *a, **k: 40.0)
    monkeypatch.setattr(PR, "_implied_vol_pct", lambda s: {"available": False,
                                                          "reason": "x"})
    monkeypatch.setattr("mas.realtime.consensus", lambda *a, **k: {
        "price": 45.0, "confirmation": "SINGLE", "usable": True,
        "n_sources": 1, "spread_pct": None, "statement": "ok"})
    d = PR.run(_req()).data
    assert "no forecast" in d["no_forecast"].lower()
    for h in d["horizons"]:
        assert "probability" not in str(h).lower()


def test_short_history_is_refused_rather_than_extrapolated(monkeypatch):
    import mas.agents.pricing as PR
    monkeypatch.setattr(PR, "_bars", lambda s, period="1y": _frame(n=10))
    r = PR.run(_req())
    assert r.status != "OK"
    assert "bars available" in r.reason


# ── registry ──────────────────────────────────────────────────────────────

def test_price_discovery_is_a_registered_capability():
    from mas.registry import CAPABILITIES
    assert "price_discovery" in CAPABILITIES


def test_the_pricing_agent_is_registered_and_keyless():
    from mas.registry import agents
    found = [a for a in agents("price_discovery", "EQUITY") if a["id"] == "pricing"]
    assert found, "the pricing agent is not registered for EQUITY"
    assert not found[0].get("requires_key")


def test_the_pricing_agent_writes_nothing():
    """A read-only agent must declare it, or planning cannot tell it apart from
    one with side effects."""
    from mas.registry import load
    assert load()["agents"]["pricing"]["writes"] == {}
