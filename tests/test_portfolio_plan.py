"""
Verification for agents/portfolio_plan.py — the Portfolio tab's overview,
diagnosis, risk-based rebalance and screener ideas — and its wiring into
/api/portfolio-brief.

Run: python3 tests/test_portfolio_plan.py

Offline/deterministic: synthetic returns from a seeded generator; the endpoint
test stubs every price, ledger, ranking, filings and screener source, so no
network and no database writes.

What must hold:
  1. ERC really equalizes risk: equal risk shares, inverse-volatility when
     uncorrelated, and less money for names that move together.
  2. Caps hold (position and sector), the account still sums to 100%, and a
     cap that can't be met with the names held is raised and SAID so.
  3. Trades: only past the drift band, shares = dollars / price, totals add
     up, and an already-balanced book produces no trades.
  4. Holdings with too little history or no price are kept, not guessed.
  5. A buy the engine disagrees with (EXIT/TRIM) is flagged, not hidden.
  6. The diagnosis names the real problems in plain words, and says so when
     there are none.
  7. Ideas never include a held name, a filing concern or a low score, and a
     low-correlation candidate is marked as a diversifier.
  8. The endpoint returns the plan beside the brief, and a plan failure never
     breaks the brief.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from agents.portfolio_plan import (DRIFT_BAND_PCT, MIN_OBS, build_plan, erc_weights,
                                   risk_shares)

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {name:70s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    # Fails the process, not just the transcript: a check that only prints
    # leaves a pytest run green regardless of what it found.
    assert cond, name


IDX = pd.bdate_range("2025-01-02", periods=250)


def _series(seed, vol=0.012, factor=None, beta=0.0, n=250):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, vol, n)
    if factor is not None:
        r = r + beta * factor[:n]
    return pd.Series(r, index=IDX[:n])


def _h(t, sector, shares, price, cost, action="HOLD", reason=None):
    return {"ticker": t, "sector": sector, "shares": shares, "avg_cost": cost,
            "current_price": price, "market_value": shares * price,
            "position_action": action, "reasons": [reason] if reason else []}


def _book():
    """61% in one tech name, two correlated tech names, an EXIT, 10% cash."""
    f = np.random.default_rng(99).normal(0, 0.015, 250)
    rets = {"NVDA": _series(1, 0.010, f, 1.8), "AMD": _series(2, 0.010, f, 1.6),
            "JNJ": _series(3, 0.008), "XOM": _series(4, 0.012)}
    brief = {"holdings": [
        _h("NVDA", "Technology", 100, 180.0, 90.0, "TRIM", "Overweight"),
        _h("AMD", "Technology", 40, 150.0, 100.0),
        _h("JNJ", "Healthcare", 10, 160.0, 150.0),
        _h("XOM", "Energy", 10, 110.0, 100.0, "EXIT", "Thesis broken")],
        "portfolio": {}}
    return brief, rets


def _trade(plan, t):
    return next(r for r in plan["rebalance"]["trades"] if r["ticker"] == t)


# ── 1. The math ───────────────────────────────────────────────────────────

def test_erc_equalizes_risk_and_reduces_to_inverse_vol():
    vol = np.array([0.3, 0.3, 0.3])
    corr = np.array([[1, .9, 0], [.9, 1, 0], [0, 0, 1]])
    cov = np.outer(vol, vol) * corr
    w = erc_weights(cov)
    rs = risk_shares(w, cov)
    check("weights sum to 1", abs(w.sum() - 1) < 1e-9)
    check("each holding carries the same share of risk", np.allclose(rs, 1 / 3, atol=1e-6), str(rs.round(4)))
    check("two names that move together get less than the independent one",
          w[0] < w[2] and w[1] < w[2], str(w.round(3)))
    d = np.diag([0.1 ** 2, 0.2 ** 2, 0.4 ** 2])
    inv = 1 / np.array([0.1, 0.2, 0.4])
    check("uncorrelated case is inverse-volatility", np.allclose(erc_weights(d), inv / inv.sum(), atol=1e-6))
    check("one holding is 100%", erc_weights(np.array([[0.04]]))[0] == 1.0)


# ── 2. Caps and feasibility ──────────────────────────────────────────────

def test_caps_hold_and_the_account_sums_to_100():
    brief, rets = _book()
    plan = build_plan(brief, rets, cash_usd=3000, crypto_usd=500)
    rb = plan["rebalance"]
    targets = {r["ticker"]: r["target_pct"] for r in rb["trades"]}
    check("no position above the 25% cap", max(targets.values()) <= 25.0 + 0.01, str(targets))
    tech = targets["NVDA"] + targets["AMD"]
    check("Technology at or under the 40% sector cap", tech <= 40.0 + 0.05, f"{tech:.2f}")
    check("targets + cash = 100%", abs(sum(targets.values()) + rb["cash_target_pct"] - 100) < 0.1)
    check("cash kept at today's share by default", abs(rb["cash_target_pct"] - plan["overview"]["cash_pct"]) < 0.1)
    check("risk falls after the plan", rb["after"]["volatility_pct"] < rb["before"]["volatility_pct"],
          f"{rb['before']['volatility_pct']} -> {rb['after']['volatility_pct']}")
    check("crypto is counted in the total but not rebalanced",
          plan["overview"]["total_usd"] == plan["overview"]["invested_usd"] + 3000 + 500)


def test_an_unmeetable_cap_is_raised_and_said():
    rets = {t: _series(i, 0.01) for i, t in enumerate(["A", "B", "C"])}
    brief = {"holdings": [_h("A", "Technology", 10, 100, 90), _h("B", "Healthcare", 10, 100, 90),
                          _h("C", "Energy", 10, 100, 90)], "portfolio": {}}
    plan = build_plan(brief, rets)
    rb = plan["rebalance"]
    check("3 holdings: cap raised to 33.3%", abs(rb["caps"]["position_pct"] - 33.3) < 0.1, str(rb["caps"]))
    check("the raise is explained", any("position cap" in n for n in rb["notes"]), str(rb["notes"]))

    one = {"holdings": [_h(t, "Technology", 10, 100, 90) for t in ["A", "B", "C", "D", "E"]], "portfolio": {}}
    rets5 = {t: _series(10 + i) for i, t in enumerate(["A", "B", "C", "D", "E"])}
    plan1 = build_plan(one, rets5)
    check("all one sector: the sector cap is lifted, not violated silently",
          plan1["rebalance"]["caps"]["sector_pct"] >= 99.9, str(plan1["rebalance"]["caps"]))
    check("...and the note points to Ideas", any("Ideas" in n for n in plan1["rebalance"]["notes"]))


def test_money_the_caps_cant_place_stays_in_cash_and_says_why():
    rets = {t: _series(40 + i, 0.01) for i, t in enumerate(["A", "B", "C"])}
    brief = {"holdings": [_h("A", "Technology", 10, 100, 90), _h("B", "Technology", 10, 100, 90),
                          _h("C", "Healthcare", 10, 100, 90)], "portfolio": {}}
    rb = build_plan(brief, rets)["rebalance"]
    check("some money stays in cash", rb["cash_target_pct"] > 1, str(rb["cash_target_pct"]))
    note = next((n for n in rb["notes"] if "stays in cash" in n), "")
    check("the note names the binding caps and points to Ideas",
          "sector cap" in note and "stock cap" in note and "Ideas" in note, note)


def test_cash_target_is_honored():
    brief, rets = _book()
    plan = build_plan(brief, rets, cash_usd=3000, cash_target_pct=20)
    check("cash target 20%", abs(plan["rebalance"]["cash_target_pct"] - 20) < 0.1,
          str(plan["rebalance"]["cash_target_pct"]))


# ── 3. Trades ─────────────────────────────────────────────────────────────

def test_trades_respect_the_band_and_add_up():
    brief, rets = _book()
    plan = build_plan(brief, rets, cash_usd=3000)
    rb = plan["rebalance"]
    for r in rb["trades"]:
        if r["side"] == "KEEP":
            check(f"{r['ticker']} kept: drift under {DRIFT_BAND_PCT} pts or kept by rule",
                  abs(r["change_pct"]) < DRIFT_BAND_PCT or r["note"], str(r))
        else:
            price = next(h["current_price"] for h in brief["holdings"] if h["ticker"] == r["ticker"])
            check(f"{r['ticker']} shares = dollars / price", abs(r["shares"] - r["usd"] / price) < 1e-3)
    t = rb["totals"]
    buys = sum(r["usd"] for r in rb["trades"] if r["side"] == "BUY")
    sells = sum(r["usd"] for r in rb["trades"] if r["side"] == "SELL")
    check("totals match the trade list", abs(t["buy_usd"] - buys) < 0.05 and abs(t["sell_usd"] - sells) < 0.05)
    check("cash after = cash + sells - buys", abs(t["cash_after_usd"] - (3000 + sells - buys)) < 0.05)
    check("the 61% position is sold down", _trade(plan, "NVDA")["side"] == "SELL")


def test_a_balanced_book_needs_no_trades():
    rets = {t: _series(20 + i, 0.01) for i, t in enumerate(["A", "B", "C", "D"])}
    brief = {"holdings": [_h(t, s, 10, 100, 90) for t, s in
                          zip(["A", "B", "C", "D"], ["Technology", "Healthcare", "Energy", "Utilities"])],
             "portfolio": {}}
    plan = build_plan(brief, rets)
    check("equal-vol, uncorrelated, equal-weight book: nothing to trade",
          all(r["side"] == "KEEP" for r in plan["rebalance"]["trades"]),
          str([(r["ticker"], r["change_pct"]) for r in plan["rebalance"]["trades"]]))


# ── 4. Missing data is kept, not guessed ─────────────────────────────────

def test_short_history_and_unpriced_holdings_are_kept():
    brief, rets = _book()
    rets["XOM"] = _series(4, n=MIN_OBS - 20)
    brief["holdings"].append({"ticker": "NEWCO", "sector": "Unknown", "shares": 5, "avg_cost": 20.0,
                              "current_price": None, "market_value": None, "position_action": "WAIT"})
    plan = build_plan(brief, rets, cash_usd=3000)
    xom, new = _trade(plan, "XOM"), _trade(plan, "NEWCO")
    check("short history: kept at today's weight", xom["side"] == "KEEP" and xom["change_pct"] == 0, str(xom))
    check("no price: kept, valued at cost", new["side"] == "KEEP" and new["now_pct"] > 0, str(new))
    kinds = [d["kind"] for d in plan["diagnosis"]]
    check("both are reported as left out", kinds.count("not_rebalanced") == 2, str(kinds))


# ── 5. Disagreement with the engine is visible ───────────────────────────

def test_buying_what_the_engine_says_to_exit_is_flagged():
    brief, rets = _book()
    plan = build_plan(brief, rets, cash_usd=3000)
    xom = _trade(plan, "XOM")
    check("the risk plan buys XOM", xom["side"] == "BUY", str(xom))
    check("...and says the engine disagrees", xom["note"] and "EXIT" in xom["note"], str(xom["note"]))


# ── 6. Diagnosis ──────────────────────────────────────────────────────────

def test_diagnosis_names_the_problems():
    brief, rets = _book()
    brief["portfolio"]["fundamental_red_flags"] = [{"ticker": "AMD", "concerns": ["Going-concern language"]}]
    plan = build_plan(brief, rets, cash_usd=3000, crypto_usd=500)
    d = {x["kind"]: x for x in plan["diagnosis"]}
    check("position over cap", "position_over_cap" in d and "NVDA" in d["position_over_cap"]["title"])
    check("sector over cap", "sector_over_cap" in d and "Technology" in d["sector_over_cap"]["title"])
    check("engine EXIT surfaced with its reason", "Thesis broken" in (d.get("engine_exit") or {}).get("detail", ""))
    check("correlated pair", "correlated_pair" in d and {"NVDA", "AMD"} == set(d["correlated_pair"]["tickers"]))
    check("filing red flag", "filing_red_flag" in d)
    check("idle cash", "idle_cash" in d)
    check("crypto explained", "crypto_total" in d)
    sev = [x["severity"] for x in plan["diagnosis"]]
    order = {"high": 0, "medium": 1, "info": 2}
    check("most severe first", sev == sorted(sev, key=lambda s: order.get(s, 3)), str(sev))


def test_a_clean_book_says_so():
    rets = {t: _series(30 + i, 0.01) for i, t in enumerate(["A", "B", "C", "D", "E"])}
    brief = {"holdings": [_h(t, s, 10, 100, 90) for t, s in zip(
        ["A", "B", "C", "D", "E"], ["Technology", "Healthcare", "Energy", "Utilities", "Financials"])],
        "portfolio": {}}
    plan = build_plan(brief, rets)
    check("first item is the all-clear", plan["diagnosis"][0]["kind"] == "no_issues", str(plan["diagnosis"][:2]))


# ── 7. Ideas ──────────────────────────────────────────────────────────────

def _screener():
    rows = [
        {"ticker": "NVDA", "available": True, "score": 95, "industry": "Semiconductors", "filing_concerns": 0},
        {"ticker": "LOWCORR", "available": True, "score": 70, "industry": "Water Supply", "filing_concerns": 0,
         "pe": 18.2, "fcf_yield": 0.05},
        {"ticker": "HIGHCORR", "available": True, "score": 90, "industry": "Semiconductors", "filing_concerns": 0},
        {"ticker": "FLAGGED", "available": True, "score": 99, "industry": "Banks", "filing_concerns": 2},
        {"ticker": "WEAK", "available": True, "score": 40, "industry": "Retail", "filing_concerns": 0},
        {"ticker": "GONE", "available": False, "reason": "no filings"},
    ]
    return {"generated_at": "2026-10-03T00:00:00", "n": len(rows), "rows": rows}


def test_ideas_filter_and_mark_diversifiers():
    brief, rets = _book()
    f = np.random.default_rng(99).normal(0, 0.015, 250)
    cands = {"LOWCORR": _series(50, 0.01), "HIGHCORR": _series(51, 0.005, f, 1.7)}
    plan = build_plan(brief, rets, cash_usd=3000, screener=_screener(), candidate_returns=cands)
    ideas = plan["ideas"]
    names = [i["ticker"] for i in ideas["items"]]
    check("ideas available with the screener caveat", ideas["available"] and "not a recommendation" in ideas["caveat"])
    check("never a held name", "NVDA" not in names, str(names))
    check("never a filing concern or a low score", "FLAGGED" not in names and "WEAK" not in names, str(names))
    lo = next(i for i in ideas["items"] if i["ticker"] == "LOWCORR")
    hi = next(i for i in ideas["items"] if i["ticker"] == "HIGHCORR")
    check("low-correlation candidate is a diversifier", lo["diversifier"] and lo["corr_with_portfolio"] < 0.5,
          str(lo["corr_with_portfolio"]))
    check("high-correlation candidate is not", not hi["diversifier"], str(hi["corr_with_portfolio"]))
    check("diversifiers listed first", names[0] == "LOWCORR", str(names))
    check("reasons name the EXIT holding they could replace, not the TRIM one",
          any("XOM" in w for w in lo["why"]) and not any("NVDA" in w for w in lo["why"]), str(lo["why"]))
    none = build_plan(brief, rets, screener=None)
    check("no screener: ideas say why", not none["ideas"]["available"] and none["ideas"]["reason"])


# ── 8. The endpoint ───────────────────────────────────────────────────────

def _price_frame(seed):
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.012, 250))
    return pd.DataFrame({"Close": close}, index=IDX)


def _post(payload, **extra_patches):
    from test_portfolio_brief import _rec  # the brief tests' recommendation fixture
    for h in payload["holdings"]:
        h["recommendation"] = _rec(h["ticker"], current_price=h.pop("_price"))
    seeds = {}

    def fake_hist(t, period="1y"):
        seeds.setdefault(t, len(seeds) + 1)
        return _price_frame(seeds[t])

    patches = [
        patch("tools.market_data.fetch_price_history", side_effect=fake_hist),
        patch("data.prediction_ledger.calibration_report", return_value={}),
        patch("data.prediction_ledger.summary", return_value={}),
        patch("xsection.ranking.run_ranking", side_effect=RuntimeError("offline")),
        patch("stock_analysis.sweep.sweep", return_value={}),
        patch("stock_analysis.sweep.red_flags", return_value=[]),
        patch("stock_analysis.screener.latest", return_value=_screener()),
    ] + [patch(k, **v) for k, v in extra_patches.items()]
    for p in patches:
        p.start()
    try:
        from web.app import app
        return app.test_client().post("/api/portfolio-brief", json=payload)
    finally:
        for p in reversed(patches):
            p.stop()


def test_endpoint_returns_the_plan_beside_the_brief():
    resp = _post({"holdings": [{"ticker": "AAA", "shares": 50, "avg_cost": 80, "_price": 100.0},
                               {"ticker": "BBB", "shares": 10, "avg_cost": 90, "_price": 100.0},
                               {"ticker": "CCC", "shares": 10, "avg_cost": 95, "_price": 100.0}],
                  "cash_usd": 1000, "crypto_usd": 250, "max_sector_pct": 40})
    body = resp.get_json()
    check("200 OK", resp.status_code == 200, str(resp.status_code))
    check("brief still there", len(body.get("holdings") or []) == 3)
    plan = body.get("plan") or {}
    check("plan attached and available", plan.get("available") is True, str(plan.get("reason")))
    check("cash and crypto flowed into the overview",
          plan["overview"]["cash_usd"] == 1000 and plan["overview"]["crypto_usd"] == 250)
    check("trade list covers every holding", len(plan["rebalance"]["trades"]) == 3)
    check("ideas came from the screener", plan["ideas"]["available"] and plan["ideas"]["items"])


def test_a_plan_failure_never_breaks_the_brief():
    resp = _post({"holdings": [{"ticker": "AAA", "shares": 5, "avg_cost": 80, "_price": 100.0}]},
                 **{"agents.portfolio_plan.build_plan": {"side_effect": RuntimeError("boom")}})
    body = resp.get_json()
    check("brief still returned", resp.status_code == 200 and len(body.get("holdings") or []) == 1)
    check("plan reports the failure", body.get("plan", {}).get("available") is False
          and "boom" in body["plan"].get("reason", ""), str(body.get("plan")))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print(f"\n{'ALL PASS' if not FAILURES else f'{len(FAILURES)} FAILED'}")
    sys.exit(1 if FAILURES else 0)
