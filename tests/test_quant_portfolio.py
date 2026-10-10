"""quant/portfolio.py on synthetic prices (no network)."""
import numpy as np
import pytest

from quant import portfolio as Q
from quant import prices as P

DAYS = 800


def _series(seed, mu, sigma, common=None, beta=0.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(mu, sigma, DAYS)
    if common is not None:
        r = r + beta * common
    return 100 * np.cumprod(1 + r)


@pytest.fixture()
def market(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CACHE", tmp_path)
    rng = np.random.default_rng(0)
    common = rng.normal(0.0004, 0.01, DAYS)
    closes = {
        "SPY": 100 * np.cumprod(1 + common),
        "AAA": _series(1, 0.0006, 0.02, common, 1.2),     # high vol, high beta
        "BBB": _series(2, 0.0003, 0.006, common, 0.3),    # low vol
        "CCC": _series(3, 0.0004, 0.012, common, 0.8),
    }
    closes["DDD"] = closes["AAA"] * (1 + np.random.default_rng(9).normal(0, 0.001, DAYS))   # near-copy of AAA
    ts = (1600000000 + np.arange(DAYS) * 86400).tolist()

    def http(url):
        sym = url.split("/chart/")[1].split("?")[0]
        c = closes[sym].tolist()
        return {"chart": {"result": [{"timestamp": ts, "meta": {"currency": "USD"},
                                      "indicators": {"quote": [{"open": c, "high": c, "low": c, "close": c,
                                                                "volume": [1000] * DAYS}],
                                                     "adjclose": [{"adjclose": c}]}}]}}
    return http, closes


def test_risk_numbers_are_consistent(market):
    http, closes = market
    H = [{"symbol": "AAA", "shares": 10}, {"symbol": "BBB", "shares": 10}, {"symbol": "CCC", "shares": 10}]
    r = Q.risk(H, years=5, http=http)
    w = {h["symbol"]: h["weight"] for h in r["holdings"]}
    assert abs(sum(w.values()) - 1) < 1e-3 and abs(sum(h["risk_share"] for h in r["holdings"]) - 1) < 1e-3
    vol = {h["symbol"]: h["vol_ann"] for h in r["holdings"]}
    assert vol["AAA"] > vol["CCC"] > vol["BBB"]
    beta = {h["symbol"]: h["beta"] for h in r["holdings"]}
    assert beta["AAA"] > beta["CCC"] > beta["BBB"]
    p = r["portfolio"]
    assert 0 < p["var95_1d"] < p["cvar95_1d"] and p["max_drawdown"] < 0 and p["diversification_ratio"] >= 1
    assert p["var95_1d_usd"] == pytest.approx(p["var95_1d"] * r["total_value"], rel=1e-2)


def test_most_correlated_pair_is_found(market):
    http, _ = market
    r = Q.risk([{"symbol": s, "value": 1000} for s in ("AAA", "BBB", "DDD")], years=5, http=http)
    assert {r["most_correlated_pair"]["a"], r["most_correlated_pair"]["b"]} == {"AAA", "DDD"}
    assert r["most_correlated_pair"]["corr"] > 0.95


def test_min_variance_favours_the_low_vol_name_and_respects_the_cap(market):
    http, _ = market
    o = Q.optimize(["AAA", "BBB", "CCC"], "min_variance", max_weight=0.6, http=http)
    assert max(o["weights"], key=o["weights"].get) == "BBB" and o["weights"]["BBB"] <= 0.6 + 1e-6
    assert abs(sum(o["weights"].values()) - 1) < 1e-3 and o["converged"]


def test_risk_parity_equalises_risk(market):
    http, _ = market
    o = Q.optimize(["AAA", "BBB", "CCC"], "risk_parity", max_weight=1.0, http=http)
    shares = list(o["risk_share"].values())
    assert max(shares) - min(shares) < 0.03


def test_cap_is_never_below_equal_weight(market):
    http, _ = market
    o = Q.optimize(["AAA", "BBB"], "max_sharpe", max_weight=0.2, http=http)
    assert o["max_weight"] >= 0.5 and abs(sum(o["weights"].values()) - 1) < 1e-3


def test_rebalance_trades_reach_the_target(market):
    http, closes = market
    H = [{"symbol": "AAA", "value": 7000}, {"symbol": "BBB", "value": 3000}]
    rb = Q.rebalance(H, {"AAA": 0.5, "BBB": 0.5}, http=http)
    t = {x["symbol"]: x for x in rb["trades"]}
    assert t["AAA"]["usd"] == pytest.approx(-2000) and t["BBB"]["usd"] == pytest.approx(2000)
    assert rb["turnover"] == pytest.approx(0.2)


def test_projection_bands_are_ordered_and_contributions_count(market):
    http, _ = market
    H = [{"symbol": "AAA", "value": 10000}, {"symbol": "BBB", "value": 10000}]
    p = Q.project(H, years=5, monthly_contribution=0, paths=800, history_years=5, http=http)
    end = [p["percentiles"][k][-1] for k in (5, 25, 50, 75, 95)]
    assert end == sorted(end) and p["percentiles"][50][0] == 20000
    p2 = Q.project(H, years=5, monthly_contribution=500, paths=800, history_years=5, http=http)
    assert p2["median_end"] > p["median_end"] and p2["invested"] == 20000 + 500 * 60


def test_conservative_drift_recentres_the_mean(market):
    http, _ = market
    H = [{"symbol": "AAA", "value": 10000}]
    lo = Q.project(H, years=10, paths=800, history_years=5, expected_return=0.02, http=http)
    hi = Q.project(H, years=10, paths=800, history_years=5, expected_return=0.10, http=http)
    assert lo["median_end"] < hi["median_end"] and "re-centred on 2%" in lo["assumptions"]


def test_todays_empty_daily_row_is_filled_from_the_same_day_quote(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CACHE", tmp_path)
    day = 86400
    t0 = 1791552600 - 2 * day                                  # two sessions before 2026-10-09 09:30 ET
    payload = lambda when: {"chart": {"result": [{
        "timestamp": [t0, t0 + day, t0 + 2 * day],
        "meta": {"regularMarketPrice": 229.28, "regularMarketTime": when, "regularMarketDayHigh": 233.0},
        "indicators": {"quote": [{"open": [1, 2, None], "high": [1, 2, None], "low": [1, 2, None],
                                  "close": [237.47, 230.48, None], "volume": [1, 1, None]}],
                       "adjclose": [{"adjclose": [237.47, 230.48, None]}]}}]}}
    d = P.daily("ZZZ", 3, http=lambda url: payload(1791576000))          # 16:00 ET the same day
    assert str(d.index[-1].date()) == "2026-10-09" and d["adjclose"].iloc[-1] == 229.28 and d["high"].iloc[-1] == 233.0
    for f in tmp_path.iterdir():
        f.unlink()
    d = P.daily("ZZZ", 3, http=lambda url: payload(1791576000 - day))    # the quote is yesterday's: no fill
    assert str(d.index[-1].date()) == "2026-10-08"
    for f in tmp_path.iterdir():
        f.unlink()
    live = payload(1791560000)                                          # mid-session
    live["chart"]["result"][0]["meta"]["currentTradingPeriod"] = {"regular": {"end": 1791576000}}
    assert str(P.daily("ZZZ", 3, http=lambda url: live).index[-1].date()) == "2026-10-08"
