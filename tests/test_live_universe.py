"""
The live universe — today's membership, for today's picking.

The properties worth guarding are the REFUSALS and the LABELS. A live universe
contains only survivors, so the danger is not that it ranks badly, it is that
someone reads a historical result off it and believes it.
"""
from __future__ import annotations

import pandas as pd
import pytest

from xsection import live_universe as LU
from xsection.universe import UniverseIncomplete


# ── what may be in an equity cross-section ────────────────────────────────

@pytest.mark.parametrize("ticker,ok", [
    ("AAPL", True), ("MSFT", True),
    ("BRK-B", True),        # share class is common stock
    ("GOOGL", True),        # 5 letters, does not end in an ADR/warrant suffix
    ("A", True),            # single letter is a real symbol
    ("HTHIY", False),       # ADR
    ("DTEGY", False),       # ADR
    ("BEIGF", False),       # foreign ordinary
    ("DAAQW", False),       # warrant
    ("DAAQU", False),       # unit
    ("", False),
    ("BRK.B", False),       # dotted form is not the shape the gateway takes
])
def test_only_common_stock_shapes_are_candidates(ticker, ok):
    """Ranking a warrant beside a common share compares instruments with
    different payoffs."""
    assert LU._looks_like_common_stock(ticker) is ok


def test_candidates_are_size_ordered_and_start_with_mega_caps(monkeypatch):
    """SEC's ordering is undocumented, so it is verified rather than assumed —
    and it is used only to pick CANDIDATES, with liquidity confirmed separately."""
    monkeypatch.setattr(LU, "_fetch_registrants", lambda: [
        {"cik_str": 1, "ticker": "NVDA", "title": "NVIDIA"},
        {"cik_str": 2, "ticker": "HTHIY", "title": "An ADR"},
        {"cik_str": 3, "ticker": "AAPL", "title": "Apple"},
        {"cik_str": 4, "ticker": "DAAQW", "title": "A warrant"},
        {"cik_str": 5, "ticker": "MSFT", "title": "Microsoft"},
    ])
    c = LU.candidates(10)
    assert [x["ticker"] for x in c] == ["NVDA", "AAPL", "MSFT"]
    assert [x["size_rank"] for x in c] == [1, 2, 3]


def test_candidate_size_is_respected(monkeypatch):
    monkeypatch.setattr(LU, "_fetch_registrants", lambda: [
        {"cik_str": i, "ticker": f"AA{chr(65 + i)}", "title": "x"}
        for i in range(20)])
    assert len(LU.candidates(5)) == 5


# ── the refusals that keep survivorship bias out ──────────────────────────

def _provider(monkeypatch, n=3):
    monkeypatch.setattr(LU, "_fetch_registrants", lambda: [
        {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"},
        {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft"},
        {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA"},
    ])
    p = LU.LiveUniverseProvider(size=n)
    monkeypatch.setattr(p, "_sector_for", lambda t: "Technology")
    return p


def test_a_past_date_is_refused_not_answered_with_todays_members(monkeypatch):
    """Answering a historical question with current membership IS survivorship
    bias. Refusing is the whole point of the class."""
    p = _provider(monkeypatch)
    with pytest.raises(UniverseIncomplete) as e:
        p.members("2020-01-01")
    assert "survivorship bias" in str(e.value)


def test_the_provider_never_claims_survivorship_safety(monkeypatch):
    p = _provider(monkeypatch)
    assert p.survivorship_safe is False
    assert "NOT survivorship safe" in p.disclaimer()


def test_every_member_is_flagged_not_survivorship_safe(monkeypatch):
    p = _provider(monkeypatch)
    for m in p.members(p._built_on):
        assert "NOT_SURVIVORSHIP_SAFE" in m["flags"]


def test_price_coverage_is_not_mistakable_for_membership_coverage(monkeypatch):
    """Features need years of bars; membership is known for one day. Conflating
    them would let a two-year price span read as two years of membership."""
    p = _provider(monkeypatch)
    cov = p.coverage()
    assert cov["start"] < cov["end"], "the price window must span history"
    assert cov["membership_known_for"] == p._built_on
    assert "never be read as historical membership" in cov["note"]


# ── the engine contract ───────────────────────────────────────────────────

def test_members_use_the_key_the_ranking_engine_reads(monkeypatch):
    """`ticker_as_of`, not `ticker`. Getting this wrong produced a ranked table
    with no symbols in it, which looked like a scoring failure rather than a
    contract mismatch."""
    p = _provider(monkeypatch)
    m = p.members(p._built_on)[0]
    assert "ticker_as_of" in m
    for key in ("security_id", "sector", "provenance", "listing_status"):
        assert key in m


def test_provenance_is_set_so_real_prices_are_not_labelled_fixture(monkeypatch):
    """features.py defaults an unset provenance to 'fixture'. Real data carrying
    a synthetic label is worse than no label."""
    p = _provider(monkeypatch)
    assert p.members(p._built_on)[0]["provenance"] == "sec_live"


def test_security_id_is_derived_from_the_permanent_cik(monkeypatch):
    """A ticker change must not read as a different company."""
    p = _provider(monkeypatch)
    ids = {m["ticker_as_of"]: m["security_id"] for m in p.members(p._built_on)}
    assert ids["AAPL"] == "CIK0000320193"


def test_prices_return_a_series_not_a_frame(monkeypatch):
    """The contract is a Series: features.py does float(px.iloc[-1]/px.iloc[-n]),
    and a DataFrame makes that a Series and the float() a TypeError."""
    p = _provider(monkeypatch)
    idx = pd.bdate_range("2026-01-01", periods=30)
    frame = pd.DataFrame({"Close": range(30), "Volume": [1] * 30}, index=idx)
    monkeypatch.setattr("financial_data.gateway.get_bars_df",
                        lambda *a, **k: frame)
    out = p.prices("CIK0000320193", "2026-01-01", "2026-02-01")
    assert isinstance(out, pd.Series)


def test_an_unknown_security_yields_an_empty_series_not_a_crash(monkeypatch):
    """One missing name must be excluded by the feature step, not take the whole
    ranking down."""
    p = _provider(monkeypatch)
    out = p.prices("CIK9999999999", "2026-01-01", "2026-02-01")
    assert isinstance(out, pd.Series) and len(out) == 0


def test_the_benchmark_resolves_even_though_it_is_not_a_constituent(monkeypatch):
    p = _provider(monkeypatch)
    assert p._ticker_for(LU.BENCHMARK_TICKER) == LU.BENCHMARK_TICKER
    assert p.benchmark_id() == LU.BENCHMARK_TICKER


def test_fundamentals_reuse_the_existing_edgar_function(monkeypatch):
    """A second implementation of filed-date governance would be free to drift
    from the first — the mistake the algo scorer made with its thresholds."""
    from xsection.providers.edgar_features import edgar_fundamentals
    p = _provider(monkeypatch)
    assert p.fundamentals_fn() is edgar_fundamentals


def test_a_missing_sector_is_none_rather_than_guessed(monkeypatch):
    """A wrong peer group compares a company against businesses it has nothing
    to do with; the engine already handles a missing sector."""
    p = LU.LiveUniverseProvider(size=1)
    monkeypatch.setattr("tools.market_data.fetch_fundamentals",
                        lambda *a, **k: {})
    assert p._sector_for("ZZZZ") is None


# ── liquidity confirmation ────────────────────────────────────────────────

def test_liquidity_confirmation_drops_thin_names(monkeypatch):
    """The real filter. A preferred tranche or warrant slips past any
    ticker-shape rule and is caught here on traded value instead."""
    idx = pd.bdate_range("2026-01-01", periods=40)
    thick = pd.DataFrame({"Close": [100.0] * 40, "Volume": [1_000_000] * 40},
                         index=idx)
    thin = pd.DataFrame({"Close": [100.0] * 40, "Volume": [100] * 40}, index=idx)
    monkeypatch.setattr("financial_data.gateway.get_bars_df",
                        lambda t, **k: thick if t == "BIG" else thin)
    r = LU.confirm_liquidity(["BIG", "TINY"])
    assert [k["ticker"] for k in r["kept"]] == ["BIG"]
    assert r["dropped"][0]["ticker"] == "TINY"
    assert "below" in r["dropped"][0]["reason"]


def test_a_name_with_no_history_is_dropped_with_a_reason(monkeypatch):
    monkeypatch.setattr("financial_data.gateway.get_bars_df",
                        lambda t, **k: None)
    r = LU.confirm_liquidity(["NOPE"])
    assert r["kept"] == []
    assert "insufficient price history" in r["dropped"][0]["reason"]


# ── registry ──────────────────────────────────────────────────────────────

def test_the_live_universe_is_listed_and_flagged():
    from xsection.universe import list_universes
    by_id = {u["universe_id"]: u for u in list_universes()}
    assert by_id[LU.UNIVERSE_ID]["status"] == "available"
    assert by_id[LU.UNIVERSE_ID]["survivorship_safe"] is False


def test_the_real_data_pilot_is_no_longer_hidden():
    """It was reachable through get_provider() but absent from the listing,
    which made a working real-data universe look like it did not exist."""
    from xsection.universe import list_universes
    assert "production-pilot" in {u["universe_id"] for u in list_universes()}


def test_get_provider_resolves_the_live_universe():
    from xsection.universe import get_provider
    assert isinstance(get_provider(LU.UNIVERSE_ID), LU.LiveUniverseProvider)
    assert isinstance(get_provider("live"), LU.LiveUniverseProvider)
