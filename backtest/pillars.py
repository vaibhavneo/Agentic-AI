"""
Seven-Pillar Composite Investing Strategy — the deterministic layer.

Each of the Stock Agent's analysis sub-agents narrates one domain. This module
turns those six domains into DETERMINISTIC 0-100 pillar scores computed from the
same machine data each agent reads — the LLM prose stays as the explainer, the
formulas here are the only number source (charter P4). The 7th agent
(prediction) is deliberately NOT a pillar: it is the COMBINER. Feeding its LLM
scores back in would double-count the other six domains through a stochastic
blender; anyone tempted to "add the 7th pillar" later should reread this line.

Honesty architecture (the part that matters):
  BACKTESTABLE CORE   technical + algo + risk — fully derivable from price
                      history, so their combination can be tested through the
                      honest stack (CostModel, purged walk-forward, PBO,
                      ledger-denominated dSR). Registered in STRATEGY_REGISTRY.
  TRACKED-FORWARD     fundamentals (restated snapshot; EDGAR PIT upgrades the
  MODIFIERS           live pillar but PIT is not in the backtest path yet),
                      research (analyst consensus), social (reddit/stocktwits).
                      Free data has NO history for these — a "backtest" of them
                      would be fiction. They get small BOUNDED weight (±5 pts
                      each), explicit flags, and forward tracking via the
                      recommendations/outcomes ledger instead.

Weights are FIXED, TRANSPARENT v1 PRIORS — not fitted. 80% of the core goes to
the two fully-backtested meters, 20% to the partially-evidence-backed one, and
the never-backtested pillars can only tilt, never drive. Fitting weights is
allowed ONLY through walk_forward_cv with one ledger.record_trial per weight
vector tried; anything else is weight-shopping, the exact overfitting the
TrialRegistry exists to count.

Stance is LONG-ONLY (user decision): the strategy is invested or in cash.
Verbs: BUY >=70 · ACCUMULATE 60-70 · HOLD 45-60 · REDUCE 35-45 · SELL <35,
with hysteresis (enter >=65, exit <55) and a weekly decision cadence so the
composite doesn't churn away its edge against the realistic cost model.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

# ── Fixed v1 weights (see module docstring before touching these) ──────────
CORE_WEIGHTS = {"technical": 0.40, "algo": 0.40, "fundamentals": 0.20}

# ── Fundamentals scorer (Stock Analysis Agent) ─────────────────────────────
# v1     the four ratio bands below, from the latest value of each line item
# shadow v1 scores; v2 is computed alongside and recorded, never weighed
# v2     stock_analysis/scoring.py scores the pillar, with CORE_WEIGHTS_V2
#
# v2 earns a larger core weight than v1 on evidence, not preference: the
# self-improvement loop measured fundamentals as the only pillar with a
# positive forward correlation at every horizon, and the algo leg as negative
# at every horizon with no out-of-sample edge in any re-weighting
# (backtest/algo_legs.py). Promotion from shadow is governed by
# backtest/fundamentals_v2_eval.py's pre-stated rule; see
# docs/FUNDAMENTALS_V2_EVALUATION.md for the run that decided it.
FUNDAMENTALS_SCORER_DEFAULT = "shadow"
CORE_WEIGHTS_V2 = {"technical": 0.30, "algo": 0.30, "fundamentals": 0.40}


def fundamentals_scorer() -> str:
    """v1 | shadow | v2. FUNDAMENTALS_SCORER overrides the shipped default.
    Under pytest v2 is never computed unless a test asks for it — it reads
    live SEC data, and a suite must not depend on the network."""
    import os
    import sys
    mode = (os.getenv("FUNDAMENTALS_SCORER") or FUNDAMENTALS_SCORER_DEFAULT).strip().lower()
    if mode not in ("v1", "shadow", "v2"):
        mode = "v1"
    if ("pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST")) and \
            not os.getenv("STOCK_ANALYSIS_SCORER_IN_TESTS"):
        return "v1"
    return mode


def _v2_fundamentals(ticker: str, pit: Optional[Dict[str, Any]], price: Optional[float]) -> Optional[Dict[str, Any]]:
    try:
        from stock_analysis.scoring import fundamental_score
        r = fundamental_score(ticker, as_of=(pit or {}).get("as_of"), price=price)
        return r if r.get("available") else None
    except Exception:
        return None
MODIFIER_MAX_PTS = 5.0          # per modifier pillar, max tilt in points

# Which modifier pillars actually TILT the composite.
#
# `social` is computed but no longer counted. Measured across the ledger its
# correlation with forward return was +0.016 at 5 days, -0.026 at 20, and it had
# no matured observations at all at 60 — on samples of 250, 14 and 0. A modifier
# entitled to 5 composite points that cannot show a relationship to the outcome
# at any horizon is 5 points of noise, and its own input carries
# `reddit_sample_too_small` on most names.
#
# It stays SCORED rather than deleted, for the same reason a retired algo leg
# keeps firing: a pillar that stops being computed stops generating attributable
# observations and can never earn its place back, so retirement would be
# permanent regardless of later evidence. Scored-but-not-counted keeps the
# self-improvement loop able to change its mind.
MODIFIER_PILLARS = ("research",)
RETIRED_MODIFIERS = ("social",)
ENTER_THRESHOLD = 65.0          # hysteresis: go long at/above
EXIT_THRESHOLD = 55.0           # hysteresis: back to cash below
VETO_BAND = (35.0, 65.0)        # composite clamp when the risk veto fires

ACTION_BANDS = [                # (min_score_inclusive, verb) — investing verbs
    (70.0, "BUY"), (60.0, "ACCUMULATE"), (45.0, "HOLD"), (35.0, "REDUCE"), (-1.0, "SELL"),
]


def action_for(score: float) -> str:
    for lo, verb in ACTION_BANDS:
        if score >= lo:
            return verb
    return "HOLD"


def _clip(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(min(hi, max(lo, v)))


# ══════════════════════════════════════════════════════════════════════════
# Snapshot pillar scores (live path — pure arithmetic, keyless)
# ══════════════════════════════════════════════════════════════════════════

def _pillar(score: Optional[float], confidence: float, backtestable: bool,
            formula: str, inputs: Dict[str, Any], flags: Optional[list] = None) -> Dict[str, Any]:
    return {
        "score": round(_clip(score), 1) if score is not None else 50.0,
        "confidence": round(_clip(confidence, 0.0, 1.0), 2),
        "backtestable": backtestable,
        "formula": formula,
        "inputs": inputs,
        "flags": flags or [],
    }


def _risk_score(hv20: Optional[float], beta: Optional[float],
                price: Optional[float], hi52: Optional[float], lo52: Optional[float],
                short_ratio: Optional[float]) -> Dict[str, Any]:
    """Inverse-risk 0-100: 100 = calm, 0 = dangerous. Sub-scores averaged over
    what's available; missing inputs reported, never guessed."""
    subs: Dict[str, float] = {}
    if hv20 is not None:
        # 15% annualized vol -> 100 … 60% -> 0, linear
        subs["volatility"] = _clip((60.0 - float(hv20)) / (60.0 - 15.0) * 100.0)
    if beta is not None:
        # |beta-1| of 0 -> 100 … 1.5 -> 0
        subs["beta"] = _clip((1.5 - abs(float(beta) - 1.0)) / 1.5 * 100.0)
    if price and hi52 and lo52 and hi52 > lo52:
        # Mid-range is calm; the extremes are where blowups and euphoria live.
        pos = (float(price) - float(lo52)) / (float(hi52) - float(lo52))
        subs["range_position"] = _clip(100.0 - abs(pos - 0.5) * 2.0 * 60.0)  # 0.5->100, edges->40
    if short_ratio is not None and float(short_ratio) > 8.0:
        subs["short_interest_penalty"] = 20.0     # crowded short = squeeze/thesis risk
    if not subs:
        return {"score": None, "subs": subs}
    return {"score": sum(subs.values()) / len(subs), "subs": subs}


def compute_pillar_scores(
    ticker: str,
    indicators: Dict[str, Any],
    signal_summary: Dict[str, Any],
    algo_signals: Dict[str, Any],
    fundamentals: Dict[str, Any],
    reddit: Optional[Dict[str, Any]] = None,
    stocktwits: Optional[Dict[str, Any]] = None,
    pit: Optional[Dict[str, Any]] = None,
    strict_fundamentals: bool = False,
    asset_class: str = "EQUITY",
    horizon_days: Optional[int] = None,
) -> Dict[str, Any]:
    """The six pillar scores + composite for RIGHT NOW (live snapshot).

    Inputs are the exact dicts the LLM agents receive (market_data outputs);
    `pit` is an optional analyze_fundamentals_pit() result — when present and
    available, the margin/ROE/D-E sub-scores use EDGAR as-reported values and
    the caller's ledger claims can cite SEC-accession datums.

    `strict_fundamentals` (the RECOMMENDATION path sets it True): the
    fundamentals pillar is sourced ONLY through the FinancialDataGateway (EDGAR
    PIT) — the legacy yfinance accounting fields (profitMargins/returnOnEquity/
    totalDebt/trailingPE/…) are NOT used. When EDGAR is unavailable (non-filer),
    the pillar is neutral+flagged and the caller's data-confidence drops, rather
    than silently substituting restated yfinance numbers. This is the guarantee
    that a recommendation's fundamentals trace to SEC filings, not Yahoo.

    `asset_class` decides which pillars are even APPLICABLE. It defaults to
    EQUITY, so every existing caller is unaffected and equity verdicts do not
    move. For a class where a pillar's input cannot exist — a coin has no
    income statement, an index has no analyst coverage — that pillar is marked
    `applicable: False` and its weight is REDISTRIBUTED over the pillars that
    were actually measured, rather than contributing `_pillar`'s neutral 50.0.
    The difference is not cosmetic: at the equity weights an inapplicable
    fundamentals pillar would otherwise inject `50.0 * 0.20 = 10` points of
    fabricated middle into every crypto composite, pulling it toward HOLD by
    construction while flagging it in a field the composite never reads.
    """
    fundamentals = fundamentals or {}
    pillars: Dict[str, Dict[str, Any]] = {}

    # 1. TECHNICAL — the existing 0-100 voting meter, verbatim. Its vote logic
    # is mirrored bar-by-bar in technical_score_series() below (backtestable).
    pillars["technical"] = _pillar(
        signal_summary.get("score"), 1.0, True,
        "signal_summary.score (RSI/MACD/SMA/BB voting, tools/market_data.py)",
        {"score": signal_summary.get("score"), "direction": signal_summary.get("direction")},
        [] if signal_summary.get("score") is not None else ["no_technical_data"])

    # 2. ALGO — the existing quant voting meter, verbatim (mirrored vectorized).
    # Leg-level provenance for the algo pillar, so attribution can ask which
    # leg carried a decision rather than only what the blend came to.
    #
    # The legs are COMBINED here rather than in market_data because the leg
    # weights are horizon-scoped and this is the first place the horizon is
    # known. The legs themselves are price-derived and horizon-independent, so
    # computing them upstream and weighing them here puts each decision at the
    # right seam: what the market did, then what this horizon makes of it.
    from backtest import algo_legs as _al
    _algo_leg_votes = dict(algo_signals.get("algo_legs") or {})
    _algo_breadth = algo_signals.get("algo_breadth")
    _algo_leg_weights = dict(_al.DEFAULT_LEG_WEIGHTS)
    _algo_leg_source = "DEFAULT_LEG_WEIGHTS"

    if _algo_leg_votes and horizon_days is not None:
        try:
            from selfimprove.config import active as _active
            from selfimprove.config import resolve_horizon as _resolve
            from selfimprove.surface import ALGO_LEG_WEIGHTS as _ALW
            _cand = _active(_ALW, int(horizon_days))
            _res, _ = _resolve(int(horizon_days))
            if _cand and set(_cand) == set(_algo_leg_weights) and any(
                    abs(_cand[k] - _algo_leg_weights[k]) > 1e-9
                    for k in _algo_leg_weights):
                _algo_leg_weights = _cand
                _algo_leg_source = (f"selfimprove:{_res}d"
                                    + ("" if _res == int(horizon_days)
                                       else f" (asked {int(horizon_days)}d)"))
        except Exception:
            pass          # the loop is an enhancement, never a dependency

    if _algo_leg_votes:
        _recombined = _al.score_from_legs(_algo_leg_votes, _algo_leg_weights)
        # Rescore only when the weighting actually differs from the one the
        # upstream scorer already applied, so an untouched system keeps the
        # exact number market_data produced rather than a re-rounded copy.
        if _algo_leg_source != "DEFAULT_LEG_WEIGHTS":
            algo_signals = dict(algo_signals)
            algo_signals["algo_score"] = _recombined["score"]
        _algo_breadth = _recombined["breadth"]

    _algo_scorer_version = (
        _al.scorer_version(_algo_leg_weights)
        if _algo_leg_votes or _algo_breadth is not None
        else _al.LEGACY_SCORER_VERSION)

    pillars["algo"] = _pillar(
        algo_signals.get("algo_score"), 1.0, True,
        "algo_signals.algo_score (z-score/momentum/linreg/volume-price voting)",
        {"algo_score": algo_signals.get("algo_score"),
         "momentum_composite": algo_signals.get("momentum_composite"),
         "mean_reversion_zscore": algo_signals.get("mean_reversion_zscore")},
        [] if algo_signals.get("algo_score") is not None else ["no_algo_data"])

    # 3. RISK — inverse-risk score; consumed as a MULTIPLIER + veto, never as
    # additive points: risk can shrink conviction, it can never buy the stock.
    rs = _risk_score(
        algo_signals.get("historical_volatility_20d"), fundamentals.get("beta"),
        indicators.get("current_price"), fundamentals.get("fiftyTwoWeekHigh"),
        fundamentals.get("fiftyTwoWeekLow"), fundamentals.get("shortRatio"))
    veto = bool(algo_signals.get("vol_regime") == "HIGH" and algo_signals.get("vol_expanding"))
    pillars["risk"] = _pillar(
        rs["score"], 1.0 if rs["score"] is not None else 0.0, True,
        "mean(vol 15-60%% inverse, |beta-1| inverse, 52w-range position, shortRatio>8 penalty); "
        "multiplier = 0.5 + 0.5*score/100; veto when vol HIGH and expanding",
        {"subs": {k: round(v, 1) for k, v in rs["subs"].items()},
         "vol_regime": algo_signals.get("vol_regime"),
         "vol_expanding": algo_signals.get("vol_expanding")},
        (["risk_veto_active"] if veto else []) + ([] if rs["score"] is not None else ["no_risk_data"]))

    # 4. FUNDAMENTALS — quality from ratio bands (stated priors, not fitted).
    subs: Dict[str, float] = {}
    flags: list = []
    pit_ratios = (pit or {}).get("ratios") if (pit or {}).get("available") else None
    fundamentals_source = "unavailable"

    if pit_ratios:
        # EDGAR PIT, as-reported: the only source used in strict mode, and the
        # preferred source otherwise. Claims cite SEC accession numbers.
        fundamentals_source = "sec-edgar"
        flags.append("pit_fundamentals_used")
        if "net_margin" in pit_ratios:
            subs["margin"] = _clip(float(pit_ratios["net_margin"]["value"]) * 400.0)   # 25% -> 100
        if "return_on_equity" in pit_ratios:
            subs["roe"] = _clip(float(pit_ratios["return_on_equity"]["value"]) * 250.0)  # 40% -> 100
        if "debt_to_equity" in pit_ratios:
            subs["de"] = _clip(100.0 - float(pit_ratios["debt_to_equity"]["value"]) * 33.3)  # 0->100, 3->0
        if "operating_margin" in pit_ratios:
            subs["op_margin"] = _clip(float(pit_ratios["operating_margin"]["value"]) * 300.0)

    if not strict_fundamentals:
        # Non-strict (general dashboard use): value ratios + a yfinance quality
        # fallback are allowed. The recommendation path does NOT take this branch
        # — its fundamentals are SEC-only (goal: not legacy yfinance fundamentals).
        pe = fundamentals.get("trailingPE")
        if pe is not None and pe > 0:
            subs["pe"] = _clip(100.0 - (float(pe) - 10.0) * (50.0 / 25.0))  # 10->100, 35->50
        pb = fundamentals.get("priceToBook")
        if pb is not None and pb > 0:
            subs["pb"] = _clip(100.0 - (float(pb) - 1.0) * (50.0 / 4.0))    # 1->100, 5->50
        fcf, mcap = fundamentals.get("freeCashflow"), fundamentals.get("marketCap")
        if fcf is not None and mcap:
            subs["fcf_yield"] = _clip(float(fcf) / float(mcap) * 100.0 * 10.0 + 30.0)
        if not pit_ratios:
            flags.append("restated_snapshot_fundamentals")
            pm = fundamentals.get("profitMargins")
            if pm is not None:
                subs["margin"] = _clip(float(pm) * 400.0)
            roe = fundamentals.get("returnOnEquity")
            if roe is not None:
                subs["roe"] = _clip(float(roe) * 250.0)
            debt = fundamentals.get("totalDebt")
            if debt is not None and mcap:
                subs["de"] = _clip(100.0 - (float(debt) - float(fundamentals.get("totalCash") or 0))
                                   / float(mcap) * 100.0)
        rg = fundamentals.get("revenueGrowth")
        if rg is not None:
            subs["growth"] = _clip(50.0 + float(rg) * 250.0)
    elif not pit_ratios:
        # STRICT + no EDGAR (non-filer): neutral + flagged, never yfinance.
        flags.append("fundamentals_no_sec_source")

    fund_score = sum(subs.values()) / len(subs) if subs else None
    fund_conf = min(1.0, len(subs) / (4.0 if strict_fundamentals else 5.0))
    fund_formula = ("mean(EDGAR PIT margin/roe/de/op_margin) — SEC-sourced, stated priors"
                    if strict_fundamentals else
                    "mean(pe/pb/fcf_yield + margin/roe/de/growth) — stated priors")
    fund_inputs: Dict[str, Any] = {"subs": {k: round(v, 1) for k, v in subs.items()}, "coverage": len(subs),
                                   "source": fundamentals_source}
    scorer = fundamentals_scorer() if (strict_fundamentals and asset_class == "EQUITY") else "v1"
    fund_version = "fundamentals-v1"
    if scorer in ("shadow", "v2"):
        v2 = _v2_fundamentals(ticker, pit, indicators.get("current_price"))
        if v2 is not None:
            record = {"score": v2["score"], "subs": v2["subs"], "penalty": v2["penalty"],
                      "coverage": v2["coverage"], "version": v2["version"], "quality_grade": v2.get("quality_grade"),
                      "period_end": v2.get("period_end")}
            if scorer == "v2":
                fund_inputs = {"subs": v2["subs"], "coverage": v2["coverage"], "penalty": v2["penalty"],
                               "working": v2.get("working"), "source": "sec-edgar (stock_analysis)",
                               "v1_shadow": None if fund_score is None else round(fund_score, 1)}
                fund_score, fund_conf = v2["score"], v2["coverage"]
                fund_formula = ("fundamentals-v2: 0.30 earnings quality + 0.25 profitability + 0.20 cash return "
                                "+ 0.15 growth + 0.10 balance sheet − filing penalty (stock_analysis/scoring.py)")
                fund_version = v2["version"]
                flags = [f for f in flags if f != "fundamentals_no_sec_source"] + ["fundamentals_v2"]
                if fundamentals_source == "unavailable":
                    fundamentals_source = "sec-edgar"
            else:
                fund_inputs["v2_shadow"] = record
                flags = flags + ["fundamentals_v2_shadow"]
        elif scorer == "v2":
            flags = flags + ["fundamentals_v2_unavailable_fell_back_to_v1"]
    pillars["fundamentals"] = _pillar(
        fund_score, fund_conf,
        bool(pit_ratios) or fund_version != "fundamentals-v1",      # backtestable only when EDGAR-sourced (PIT)
        fund_formula, fund_inputs,
        flags if fund_score is not None else flags + ["no_fundamental_data"])

    # 5. RESEARCH — deterministic analyst-consensus proxy. The LLM's actual news
    # reading stays prose. NOT backtestable from free data: tracked forward.
    subs_r: Dict[str, float] = {}
    rec_mean = fundamentals.get("recommendationMean")
    if rec_mean is not None:
        subs_r["consensus"] = _clip((5.0 - float(rec_mean)) / 4.0 * 100.0)   # 1->100, 5->0
    tgt, price = fundamentals.get("targetMeanPrice"), indicators.get("current_price")
    if tgt and price:
        gap = (float(tgt) / float(price) - 1.0) * 100.0
        subs_r["target_gap"] = _clip(50.0 + gap * 2.5)                      # +20% -> 100, -20% -> 0
    n_analysts = fundamentals.get("numberOfAnalystOpinions") or 0
    conf_r = min(1.0, float(n_analysts) / 10.0)
    res_score = sum(subs_r.values()) / len(subs_r) if subs_r else None
    pillars["research"] = _pillar(
        res_score, conf_r, False,
        "mean(recommendationMean 1-5 inverted, analyst target gap); confidence = n_analysts/10",
        {"subs": {k: round(v, 1) for k, v in subs_r.items()}, "n_analysts": n_analysts},
        ["not_backtestable"] + ([] if subs_r else ["no_analyst_data"]))

    # 6. SOCIAL — reddit + stocktwits composite, confidence-shrunk toward 50 by
    # sample size (5 angry posts are noise, not signal). NOT backtestable.
    subs_s: Dict[str, float] = {}
    flags_s: list = ["not_backtestable"]
    if reddit and reddit.get("sentiment_score") is not None:
        mentions = int(reddit.get("mention_count") or 0)
        shrink = 1.0 if mentions >= 20 else (0.5 if mentions >= 5 else 0.0)
        if shrink == 0.0:
            flags_s.append("reddit_sample_too_small")
        raw = (float(reddit["sentiment_score"]) + 100.0) / 2.0            # -100..100 -> 0..100
        subs_s["reddit"] = 50.0 + (raw - 50.0) * shrink
    if stocktwits and stocktwits.get("total"):
        total = int(stocktwits["total"])
        shrink = min(1.0, total / 20.0)
        subs_s["stocktwits"] = 50.0 + (float(stocktwits.get("sentiment_ratio") or 50.0) - 50.0) * shrink
    if not subs_s:
        flags_s.append("no_social_data")
    soc_score = sum(subs_s.values()) / len(subs_s) if subs_s else None
    pillars["social"] = _pillar(
        soc_score, min(1.0, len(subs_s) / 2.0), False,
        "mean(reddit sentiment remapped + shrunk by mentions, stocktwits ratio shrunk by volume)",
        {"subs": {k: round(v, 1) for k, v in subs_s.items()}}, flags_s)

    # ── APPLICABILITY (the asset class decides what can be scored at all) ──
    from mas.asset_class import spec_for
    _spec = spec_for(asset_class)
    _inapplicable = set(_spec.inapplicable_pillars)
    for _name, _p in pillars.items():
        _p["applicable"] = _name not in _inapplicable
        if _name in _inapplicable:
            _p["flags"] = list(_p["flags"]) + [
                f"not_applicable_to_{_spec.asset_class.lower()}"]

    # The self-improvement loop may hold a validated, horizon-scoped override
    # of the core weights. It is consulted ONLY when a horizon is named: a
    # caller that does not say which horizon it is scoring cannot be given
    # weights tuned for one, and every existing caller keeps today's behaviour
    # exactly. Absent an override this returns CORE_WEIGHTS unchanged, so a
    # system that has never promoted anything scores as it always did.
    if fund_version != "fundamentals-v1":
        _base = dict(CORE_WEIGHTS_V2)
        _weight_source = "CORE_WEIGHTS_V2"
    else:
        _base = dict(CORE_WEIGHTS)
        _weight_source = "CORE_WEIGHTS"
    # Weights the loop learned were learned against the v1 fundamentals score;
    # they do not carry over to a different scorer, so v2 runs on its own.
    if horizon_days is not None and fund_version == "fundamentals-v1":
        try:
            from selfimprove.config import active as _active_weights
            from selfimprove.surface import PILLAR_WEIGHTS as _PW
            from selfimprove.config import resolve_horizon as _resolve
            _resolved, _note = _resolve(int(horizon_days))
            _override = _active_weights(_PW, int(horizon_days))
            if _override and set(_override) == set(_base) and \
                    any(abs(_override[k] - _base[k]) > 1e-9 for k in _base):
                _base = _override
                # Name the horizon the weights were LEARNED at, not the one
                # asked for. A reader comparing two decisions needs to know
                # when one was scored with parameters from a different horizon.
                _weight_source = (f"selfimprove:{_resolved}d"
                                  + ("" if _resolved == int(horizon_days)
                                     else f" (asked {int(horizon_days)}d)"))
        except Exception:
            # The loop is an enhancement, never a dependency. If its store is
            # unreachable the desk must still score, on the shipped weights.
            pass

    # Redistribute the weight of inapplicable core pillars over the rest, so
    # the composite is the weighted mean of what was MEASURED.
    _live = {k: w for k, w in _base.items() if k not in _inapplicable}
    _live_total = sum(_live.values())
    weights = ({k: w / _live_total for k, w in _live.items()}
               if _live_total > 0 else {})

    # ── COMBINE (the prediction agent's seat at this table) ────────────────
    core = (sum(weights[k] * pillars[k]["score"] for k in weights)
            if weights else 50.0)
    modifiers = 0.0
    for name in MODIFIER_PILLARS:
        if name in _inapplicable:
            continue
        p = pillars[name]
        modifiers += (p["score"] - 50.0) / 50.0 * MODIFIER_MAX_PTS * p["confidence"]
    risk_mult = 0.5 + 0.5 * pillars["risk"]["score"] / 100.0
    composite = 50.0 + (_clip(core + modifiers) - 50.0) * risk_mult
    if veto:
        composite = _clip(composite, VETO_BAND[0], VETO_BAND[1])
    composite = round(_clip(composite), 1)

    return {
        "ticker": ticker.upper(),
        "pillars": pillars,
        "lanes": signal_lanes(pillars),
        "core_score": round(core, 1),
        "modifier_pts": round(modifiers, 2),
        "risk_multiplier": round(risk_mult, 3),
        "risk_veto": veto,
        "composite": composite,
        "action": action_for(composite),
        "weights": {k: round(v, 4) for k, v in weights.items()},
        # Stated so a reader can see that a pillar shown with a score
        # contributed nothing, rather than inferring it from the arithmetic.
        "modifier_pillars": list(MODIFIER_PILLARS),
        "retired_modifiers": list(RETIRED_MODIFIERS),
        # Which SCORER produced the algo leg of this composite. Recorded because
        # experiments.manifest_hash() fingerprints the variant registry, not the
        # scorer, so without this a ledger query could not separate rows scored
        # by the vote-ratio from rows scored by the fixed denominator — and
        # calibration would average two different scorers into one number.
        "algo_scorer_version": _algo_scorer_version,
        # Which fundamentals scorer, and in which mode. A v2 row and a v1 row
        # are different measurements and must stay separable in the ledger.
        "fundamentals_scorer_version": fund_version,
        "fundamentals_scorer_mode": scorer,
        "algo_legs": _algo_leg_votes,
        "algo_breadth": _algo_breadth,
        "algo_leg_weights": {k: round(float(v), 4)
                             for k, v in _algo_leg_weights.items()},
        "algo_leg_weight_source": _algo_leg_source,
        # Which weighting produced this score. A snapshot frozen without it
        # cannot be attributed later: future attribution would assume the
        # shipped weights and silently mis-assign credit for every decision
        # made under an override.
        "weight_source": _weight_source,
        "nominal_weights": dict(CORE_WEIGHTS),
        "asset_class": _spec.asset_class,
        "inapplicable_pillars": sorted(_inapplicable),
        "composite_scorable": bool(weights),
        "modifier_max_pts": MODIFIER_MAX_PTS,
    }


# ══════════════════════════════════════════════════════════════════════════
# Signal lanes — the honesty split, as an interface rather than a convention
# ══════════════════════════════════════════════════════════════════════════
# The distinction between "this was validated" and "this can only be tracked"
# has always been real here (the per-pillar `backtestable` flag, and
# recommendation.py's social_research_tracked_forward_only), but it lived as a
# convention readers had to reconstruct. Naming it makes the guarantee legible
# at the boundary: anything in TRACKED_FORWARD is structurally incapable of
# driving a decision on its own, and the numbers below say so explicitly.

VALIDATED_LANE = ("technical", "algo", "risk")
TRACKED_FORWARD_LANE = ("fundamentals", "research", "social")

LANE_BASIS = {
    "validated": ("Derivable bar-by-bar from price history, so the combination is "
                  "testable through the honest stack: cost model, purged "
                  "walk-forward, PBO, ledger-denominated dSR."),
    "tracked_forward": ("Free data carries no usable history for these, so a "
                        "backtest would be fiction. Bounded weight, explicit "
                        "flags, and forward tracking through the outcomes ledger "
                        "instead."),
}


def signal_lanes(pillars: Dict[str, Any]) -> Dict[str, Any]:
    """Group the computed pillars by what kind of evidence stands behind them.

    Reports the WEIGHT each lane can actually move, which is the number that
    makes the guarantee checkable rather than merely stated: the validated lane
    carries the core weights, while the tracked-forward lane is capped at
    MODIFIER_MAX_PTS per pillar and cannot exceed that no matter what it says.
    Fundamentals sits in the tracked lane but does carry core weight — it is the
    one pillar whose lane and influence disagree, so it is called out rather
    than quietly averaged into either side.
    """
    def entry(name: str) -> Dict[str, Any]:
        p = pillars.get(name) or {}
        return {"pillar": name, "score": p.get("score"),
                "confidence": p.get("confidence"),
                "backtestable": p.get("backtestable"),
                "flags": p.get("flags", [])}

    validated = [entry(n) for n in VALIDATED_LANE if n in pillars]
    tracked = [entry(n) for n in TRACKED_FORWARD_LANE if n in pillars]

    # How much of the composite each lane can actually move.
    validated_weight = sum(CORE_WEIGHTS.get(n, 0.0) for n in VALIDATED_LANE)
    tracked_core_weight = sum(CORE_WEIGHTS.get(n, 0.0) for n in TRACKED_FORWARD_LANE)
    modifier_ceiling = MODIFIER_MAX_PTS * sum(
        1 for n in ("social", "research") if n in pillars)

    return {
        "validated": {
            "pillars": validated,
            "core_weight": round(validated_weight, 2),
            "basis": LANE_BASIS["validated"],
        },
        "tracked_forward": {
            "pillars": tracked,
            "core_weight": round(tracked_core_weight, 2),
            "max_modifier_pts": round(modifier_ceiling, 1),
            "basis": LANE_BASIS["tracked_forward"],
        },
        # Stated once, here, so no consumer has to infer it: fundamentals is
        # tracked-forward evidence holding core weight. That is a deliberate
        # v1 choice (EDGAR PIT is real, just not in the backtest path yet),
        # not an oversight - see the module docstring.
        "caveat": ("fundamentals carries core weight "
                   f"({CORE_WEIGHTS.get('fundamentals', 0)}) but is not in the "
                   "backtested path; social and research can only tilt, never drive."),
    }


# ══════════════════════════════════════════════════════════════════════════
# Vectorized backtestable core (technical + algo + risk over full history)
# ══════════════════════════════════════════════════════════════════════════
# These mirror the LIVE vote logic bar-by-bar using the same `ta` library the
# live path uses, so the last bar of each series equals the live meter — a
# consistency test enforces that. Rounding mirrors the live path (values are
# rounded before threshold comparison) so boundary bars can't diverge.

def technical_score_series(df: pd.DataFrame) -> pd.Series:
    """Bar-by-bar mirror of compute_signal_summary's voting (the vote-bearing
    subset: RSI, MACD cross+hist, SMA20/50/200, golden/death, BB %B — the
    volume/ADX lines in the live function add prose but zero votes today)."""
    import ta

    close = df["Close"].astype(float)
    n = len(close)
    idx = df.index

    rsi = ta.momentum.RSIIndicator(close, 14).rsi().round(4)
    macd_ind = ta.trend.MACD(close, 26, 12, 9)
    macd, macd_sig = macd_ind.macd().round(4), macd_ind.macd_signal().round(4)
    macd_hist = macd_ind.macd_diff().round(4)
    sma20 = ta.trend.sma_indicator(close, 20).round(4)
    sma50 = ta.trend.sma_indicator(close, 50).round(4)
    sma200 = ta.trend.sma_indicator(close, 200).round(4) if n >= 200 else pd.Series(np.nan, index=idx)
    bb = ta.volatility.BollingerBands(close, 20, 2)
    bb_up, bb_lo = bb.bollinger_hband().round(4), bb.bollinger_lband().round(4)

    bull = pd.Series(0.0, index=idx)
    bear = pd.Series(0.0, index=idx)

    # RSI votes (live: truthiness guard means NaN -> no vote)
    r_ok = rsi.notna()
    bull += (r_ok & (rsi < 30)) * 2 + (r_ok & (rsi > 55) & (rsi <= 70)) * 1
    bear += (r_ok & (rsi > 70)) * 2 + (r_ok & (rsi < 45) & (rsi >= 30)) * 1

    # MACD cross (live sets the key only when both values truthy)
    m_ok = macd.notna() & macd_sig.notna()
    bull += (m_ok & (macd > macd_sig)) * 2
    bear += (m_ok & (macd <= macd_sig)) * 2
    h_ok = macd_hist.notna()
    bull += (h_ok & (macd_hist > 0)) * 1
    bear += (h_ok & (macd_hist < 0)) * 1

    # SMA votes. Live quirk mirrored deliberately: a missing sma20/50 key makes
    # `if indicators.get(...)` falsy -> the ELSE branch fires -> a bear vote.
    bull += (sma20.notna() & (close > sma20)) * 1
    bear += (~(sma20.notna() & (close > sma20))) * 1
    bull += (sma50.notna() & (close > sma50)) * 1
    bear += (~(sma50.notna() & (close > sma50))) * 1
    # sma200 uses if/elif-is-False: NaN -> genuinely no vote either way.
    s200_ok = sma200.notna()
    bull += (s200_ok & (close > sma200)) * 2
    bear += (s200_ok & (close <= sma200)) * 2

    # Golden/death cross
    gd_ok = sma50.notna() & sma200.notna()
    bull += (gd_ok & (sma50 > sma200)) * 2
    bear += (gd_ok & (sma50 <= sma200)) * 2

    # Bollinger %B extremes
    bb_ok = bb_up.notna() & bb_lo.notna() & ((bb_up - bb_lo) > 0)
    bb_pct = ((close - bb_lo) / (bb_up - bb_lo) * 100).round(1)
    bull += (bb_ok & (bb_pct < 10)) * 1
    bear += (bb_ok & (bb_pct > 90)) * 1

    total = bull + bear
    score = (bull / total.replace(0, np.nan) * 100).fillna(50.0)
    # Live does int() truncation; mirror it for exact last-bar equality.
    return score.apply(math.floor).astype(float)


def algo_score_series(df: pd.DataFrame,
                      leg_weights: Optional[Dict[str, float]] = None) -> pd.Series:
    """Bar-by-bar algo score, delegating to backtest.algo_legs.

    This used to hold its own copy of the voting thresholds, mirroring
    compute_algo_signals. Two copies of the same numbers is how a backtest comes
    to measure a strategy that is not the one running: when the live scorer
    moved to a fixed denominator, this series kept returning the vote-ratio, and
    the last-bar consistency test caught it at series=100 against live=64. There
    is now one implementation and both paths call it.

    Monte Carlo and candlestick patterns still contribute zero votes, as in the
    live scorer, so they are absent here too.
    """
    from backtest.algo_legs import score_series
    return score_series(df, weights=leg_weights).apply(math.floor).astype(float)


def risk_mult_series(prices: pd.Series) -> pd.Series:
    """Rolling risk multiplier in [0.5, 1.0] from 20d annualized volatility
    (the series version uses vol only; the snapshot pillar adds beta/52w/short
    ratio, which have no free history — documented asymmetry)."""
    returns = prices.astype(float).pct_change()
    hv20 = (returns.rolling(20).std() * math.sqrt(252) * 100).round(2)
    score = ((60.0 - hv20) / 45.0 * 100.0).clip(0.0, 100.0)
    return (0.5 + 0.5 * score / 100.0).fillna(0.75)   # unknown vol -> middle


def seven_pillar_core_strategy(df: pd.DataFrame, enter: float = ENTER_THRESHOLD,
                               exit: float = EXIT_THRESHOLD) -> pd.Series:
    """The BACKTESTABLE core as a {0,1} long-only signal for the engine.

    core = (0.5*technical + 0.5*algo) scaled around 50 by the risk multiplier —
    the snapshot's fundamentals term (0.20 weight) is ABSENT here because PIT
    fundamentals are not in the backtest path yet; tech/algo renormalize to
    0.5/0.5. This means "the backtested composite" always refers to THIS core,
    never the full snapshot composite (which includes untestable modifiers).

    Weekly decision cadence: the score is sampled at each week's last bar and
    held. Hysteresis: enter at >= `enter`, stay until < `exit`. The engine's
    own .shift(1) then delays execution to the NEXT bar, so a decision made on
    Friday's close earns returns starting Monday — point-in-time correct.

    Defaults (65/55, weekly) are pre-committed priors. If they backtest badly,
    that result is REPORTED (a dead trial in the registry), not tuned away.
    """
    tech = technical_score_series(df)
    algo = algo_score_series(df)
    core = 0.5 * tech + 0.5 * algo
    mult = risk_mult_series(df["Close"])
    score = 50.0 + (core - 50.0) * mult

    # Weekly cadence: keep only each week's last observation, then hold (ffill).
    weekly_last = score.groupby(pd.Grouper(freq="W-FRI")).tail(1)
    decision = weekly_last.reindex(score.index).ffill()

    # Hysteresis state machine (long-only): enter >= enter, exit < exit.
    pos = np.zeros(len(decision))
    holding = 0.0
    vals = decision.to_numpy()
    for i in range(len(vals)):
        v = vals[i]
        if np.isnan(v):
            pos[i] = holding
            continue
        if holding == 0.0 and v >= enter:
            holding = 1.0
        elif holding == 1.0 and v < exit:
            holding = 0.0
        pos[i] = holding
    return pd.Series(pos, index=df.index)
