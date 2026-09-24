"""
The real-time layer. The tests that matter here are the REFUSALS: a live quote
path is only an improvement over settled bars if it declines to pass a bad
print through to a prediction.

Everything below is offline by construction — `consensus` is driven through a
stubbed `_fetch_one` — because a test whose assertions depend on a live market
either fails at 2am or asserts nothing.
"""
from __future__ import annotations

import pytest

from mas import realtime as RT
from financial_data.schemas import KINDS
from financial_data.gateway import list_providers


def _q(provider, price, vendor=None):
    return {"provider": provider, "price": price, "as_of": None,
            "vendor": vendor or RT.VENDOR_GROUP.get(provider, provider),
            "extra": {}}


def _stub(monkeypatch, mapping):
    """Drive consensus from a {provider: quote_or_None} map."""
    monkeypatch.setattr(RT, "_fetch_one",
                        lambda prov, sym: mapping.get(prov))


# ── registry wiring ───────────────────────────────────────────────────────

def test_quote_and_intraday_are_registered_kinds():
    assert "quote" in KINDS and "intraday" in KINDS


def test_a_quote_provider_is_never_point_in_time_capable():
    """A vendor that claimed it could replay a past instant's quote would be
    lying, and the gateway would stamp as_of_honored=True on the strength of
    the claim. Guard the registry, not just the code."""
    for p in list_providers("quote"):
        assert "quote" not in (p.get("pit_capable") or []), (
            f"{p['id']} claims quote is point-in-time capable")


def test_every_quote_provider_declares_a_vendor_group():
    """An unmapped provider defaults to its own id as its vendor group, which
    would silently upgrade CROSS_PATH to CROSS_VENDOR — the exact overclaim
    this layer exists to prevent."""
    for p in list_providers("quote"):
        assert p["id"] in RT.VENDOR_GROUP, (
            f"{p['id']} serves quotes but has no VENDOR_GROUP entry")


# ── the refusals ──────────────────────────────────────────────────────────

def test_disagreement_beyond_tolerance_returns_no_price(monkeypatch):
    _stub(monkeypatch, {"yfinance-rt": _q("yfinance-rt", 100.0),
                        "yahoo-chart": _q("yahoo-chart", 140.0)})
    c = RT.consensus("AAPL", asset_class="EQUITY")
    assert c["confirmation"] == RT.DISAGREEMENT
    assert c["usable"] is False
    assert c["price"] is None, "a disagreed price must not be returned"
    assert "bad print" in c["statement"]


def test_price_accessor_is_none_on_disagreement(monkeypatch):
    _stub(monkeypatch, {"yfinance-rt": _q("yfinance-rt", 100.0),
                        "yahoo-chart": _q("yahoo-chart", 140.0)})
    assert RT.price("AAPL", asset_class="EQUITY") is None


def test_consensus_reports_a_traded_price_never_a_blend(monkeypatch):
    """Even when sources agree, the reported price must be one a venue
    actually printed. A mean of two feeds is a third number nobody traded at,
    and it would not reconcile against any tape afterwards."""
    _stub(monkeypatch, {"yfinance-rt": _q("yfinance-rt", 100.0),
                        "yahoo-chart": _q("yahoo-chart", 100.4)})
    c = RT.consensus("AAPL", asset_class="EQUITY")
    assert c["usable"] is True, "0.4% is inside the 0.5% equity tolerance"
    assert c["price"] in (100.0, 100.4)
    assert c["price"] != 100.2, "reported a blend rather than a printed price"


def test_no_sources_is_unavailable_not_a_zero(monkeypatch):
    _stub(monkeypatch, {})
    c = RT.consensus("AAPL", asset_class="EQUITY")
    assert c["confirmation"] == RT.UNAVAILABLE
    assert c["price"] is None and c["usable"] is False


# ── the honesty of the confirmation grade ─────────────────────────────────

def test_same_vendor_agreement_is_cross_path_not_cross_vendor(monkeypatch):
    """Two Yahoo endpoints agreeing is not confirmation. This is the assertion
    the whole module exists for."""
    _stub(monkeypatch, {"yfinance-rt": _q("yfinance-rt", 100.0),
                        "yahoo-chart": _q("yahoo-chart", 100.02)})
    c = RT.consensus("AAPL", asset_class="EQUITY")
    assert c["confirmation"] == RT.CROSS_PATH
    assert c["usable"] is True
    assert "same vendor" in c["statement"]


def test_cross_path_for_an_equity_names_the_key_that_would_fix_it(monkeypatch):
    _stub(monkeypatch, {"yfinance-rt": _q("yfinance-rt", 100.0),
                        "yahoo-chart": _q("yahoo-chart", 100.02)})
    c = RT.consensus("AAPL", asset_class="EQUITY")
    assert "FINNHUB_API_KEY" in c["statement"]


def test_genuinely_independent_vendors_earn_cross_vendor(monkeypatch):
    _stub(monkeypatch, {"finnhub-quote": _q("finnhub-quote", 100.0),
                        "yfinance-rt": _q("yfinance-rt", 100.1)})
    c = RT.consensus("AAPL", asset_class="EQUITY")
    assert c["confirmation"] == RT.CROSS_VENDOR


def test_one_source_is_single_and_says_it_is_uncorroborated(monkeypatch):
    _stub(monkeypatch, {"yfinance-rt": _q("yfinance-rt", 100.0)})
    c = RT.consensus("AAPL", asset_class="EQUITY")
    assert c["confirmation"] == RT.SINGLE
    assert c["usable"] is True
    assert "uncorroborated" in c["statement"]


# ── asset class governs tolerance ─────────────────────────────────────────

def test_crypto_tolerates_a_spread_that_would_fail_an_equity(monkeypatch):
    """A single venue's book and a cross-exchange composite differ by bps
    continuously. Applying the equity tolerance to crypto would report a
    permanent false anomaly."""
    pair = {"crypto-spot": _q("crypto-spot", 100.0),
            "yfinance-rt": _q("yfinance-rt", 100.7)}
    _stub(monkeypatch, pair)
    assert RT.consensus("BTC-USD", asset_class="CRYPTO")["usable"] is True
    _stub(monkeypatch, {"yfinance-rt": _q("yfinance-rt", 100.0),
                        "yahoo-chart": _q("yahoo-chart", 100.7)})
    assert RT.consensus("AAPL", asset_class="EQUITY")["usable"] is False


def test_asset_class_is_inferred_when_not_supplied(monkeypatch):
    _stub(monkeypatch, {"crypto-spot": _q("crypto-spot", 100.0)})
    assert RT.consensus("BTC-USD")["asset_class"] == "CRYPTO"


def test_every_asset_class_with_sources_has_a_tolerance():
    for cls in RT.SOURCES_FOR_CLASS:
        assert cls in RT.TOLERANCE_PCT, f"{cls} has sources but no tolerance"


# ── provider-level guards ─────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_a_nonpositive_tick_never_becomes_a_price(monkeypatch, bad):
    """Finnhub returns c=0 for an uncovered symbol; yfinance can return 0 on a
    bad session. Zero formats as a number and would reach a prediction."""
    from financial_data.providers import finnhub_quote as FQ
    monkeypatch.setattr(FQ, "get_key", lambda *a, **k: "test-token")
    monkeypatch.setattr(FQ, "get_text",
                        lambda url, timeout=10: '{"c": %s, "pc": 10}' % bad)
    r = FQ.fetch("quote", ["AAPL"])
    assert r["data"] == []
    assert r["unavailable"] and "AAPL" in r["unavailable"][0]["symbol"]


def test_crypto_symbol_splitting_handles_the_common_spellings():
    from financial_data.providers.crypto_spot import _split
    assert _split("BTC-USD") == ("BTC", "USD")
    assert _split("BTCUSD") == ("BTC", "USD")
    assert _split("ETHUSDT") == ("ETH", "USDT")
    assert _split("SOL") == ("SOL", "USD")
