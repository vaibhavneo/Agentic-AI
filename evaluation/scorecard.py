"""
The prediction scorecard — what the desk said, against what happened.

Four questions, each graded in the frame the claim was made in:

  RANKING      Did higher-scored names beat lower-scored names against SPY on
               the same day? (per-date Spearman of composite vs excess return,
               bullish-minus-bearish spread, top-vs-bottom third). This is the
               stock-picking question, and it is market-neutral.
  DIRECTION    Did the stock move the way the call said? Graded twice: on the
               raw price (what a holder experiences) and against SPY (what the
               desk can claim credit for). In a falling quarter every bullish
               call loses on price; only the second frame separates skill from
               the market.
  PROBABILITY  Is p_up (and P(beat SPY), once frozen) honest? Brier against two
               baselines that need no hindsight: always 50%, and the up-rate
               seen in outcomes that had matured before the call.
  CONFIDENCE   Did HIGH/MEDIUM/LOW labels deliver what they claimed?

Significance is computed across CALL DATES (see stats.py), and every verdict
also needs MIN_EFFECTIVE_OBS independent windows — the same bar the
calibration and self-improvement gates use. The rules are constants stated
here before any number is read; tests pin them so they cannot drift toward
whatever the ledger happens to show.

Read-only. Nothing here feeds a score, a weight or a gate; the feedback edge is
intelligence/calibration (p_up) and intelligence/outperform (P(beat SPY)),
which carry their own out-of-sample gates.
"""
from __future__ import annotations

import bisect
import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from intelligence.calibration import MIN_EFFECTIVE_OBS, effective_sample_size

from .stats import mean, r, spearman, t_stat

# ── Pre-stated rules ──────────────────────────────────────────────────────
T_SIGNIFICANT = 2.0           # |t| on the across-date mean
MIN_DATES = 5                 # fewer usable call dates -> INSUFFICIENT
MIN_NAMES_PER_DATE = 8        # a ranking needs a cross-section
MIN_WINDOWS = MIN_EFFECTIVE_OBS

BULLISH = {"BUY", "ACCUMULATE", "LONG", "STRONG_BUY"}
BEARISH = {"SELL", "REDUCE", "SHORT", "AVOID", "STRONG_SELL"}
PILLARS = ("technical", "algo", "fundamentals", "risk", "research", "social")
CONF_LEVELS = ("HIGH", "MEDIUM", "LOW", "NONE")
P_BINS = ((0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01))


# ── Data ──────────────────────────────────────────────────────────────────

def _json(v: Any) -> Dict[str, Any]:
    if not v:
        return {}
    try:
        out = json.loads(v) if isinstance(v, str) else v
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


def _hp(d: Dict[str, Any], h: int) -> Optional[float]:
    v = d.get(str(h), d.get(h))
    return None if v is None else float(v)


def load(horizon: int, source: str = "live") -> List[Dict[str, Any]]:
    """Every matured, genuine (non-quarantined) call at one horizon, flat."""
    from data import prediction_ledger as pl

    conn = pl._conn()
    try:
        rows = [dict(x) for x in conn.execute(
            f"""SELECT s.snapshot_id, s.ticker, s.action, substr(s.created_at,1,10) AS call_date,
                       s.conf_statistical_edge AS conf, s.edge_score, s.sector,
                       s.pillars_json, s.horizon_probabilities_json AS hp,
                       json_extract(s.frozen_json, '$.composite') AS composite,
                       json_extract(s.frozen_json, '$.core_score') AS core_score,
                       json_extract(s.frozen_json, '$.modifier_pts') AS modifier_pts,
                       json_extract(s.frozen_json, '$.outperform_probabilities') AS op,
                       o.raw_return_pct AS raw, o.excess_return_pct AS excess,
                       o.as_of_date AS outcome_date, o.direction_correct
                  FROM prediction_outcomes o
                  JOIN prediction_snapshots s ON s.snapshot_id = o.snapshot_id
                 WHERE o.horizon_days=? AND o.matured=1 AND o.raw_return_pct IS NOT NULL
                       {pl._source_where(source)}""",
            (horizon,)).fetchall()]
    finally:
        conn.close()
    return [_record(x, horizon) for x in rows]


def _record(x: Dict[str, Any], h: int) -> Dict[str, Any]:
    action = str(x.get("action") or "").upper()
    excess = x.get("excess")
    return {
        "snapshot_id": x.get("snapshot_id"),
        "ticker": x.get("ticker"), "action": action,
        "side": 1 if action in BULLISH else (-1 if action in BEARISH else 0),
        "call_date": x.get("call_date"), "outcome_date": x.get("outcome_date"),
        "conf": x.get("conf") or "NONE", "edge_score": x.get("edge_score"),
        "sector": x.get("sector") or "unknown",
        "composite": None if x.get("composite") is None else float(x["composite"]),
        "core_score": x.get("core_score"), "modifier_pts": x.get("modifier_pts"),
        "pillars": {k: v for k, v in _json(x.get("pillars_json")).items() if v is not None},
        "p_up": _hp(_json(x.get("hp")), h),
        "p_beat": _hp(_json(x.get("op")), h),
        "raw": float(x["raw"]),
        "excess": None if excess is None else float(excess),
        "went_up": 1.0 if float(x["raw"]) > 0 else 0.0,
        "beat": None if excess is None else (1.0 if float(excess) > 0 else 0.0),
    }


def _by_date(records: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    g: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for x in records:
        if x.get("call_date"):
            g[x["call_date"]].append(x)
    return dict(sorted(g.items()))


def _series_stats(points: List[tuple], horizon: int) -> Dict[str, Any]:
    """[(call_date, value)] -> mean, overlap-corrected t, and the independent
    windows among THESE dates (not the ledger's): a verdict is only as
    independent as the dates that actually entered it."""
    values = [v for _, v in points]
    dates = [d for d, _ in points]
    return {"mean": r(mean(values)), "t": r(t_stat(values, horizon - 1), 2),
            "n_dates": len(values),
            "independent_windows": effective_sample_size(dates, horizon) if dates else 0}


# ── Metrics ───────────────────────────────────────────────────────────────

def coverage(records: Sequence[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    dates = sorted({x["call_date"] for x in records if x.get("call_date")})
    return {"calls": len(records), "call_dates": len(dates),
            "tickers": len({x["ticker"] for x in records}),
            "independent_windows": effective_sample_size(dates, horizon) if dates else 0,
            "first_call": dates[0] if dates else None, "last_call": dates[-1] if dates else None}


def ranking(records: Sequence[Dict[str, Any]], horizon: int,
            score=lambda x: x.get("composite")) -> Dict[str, Any]:
    """Market-neutral: each date's names against each other, then across dates."""
    ics: List[tuple] = []
    spreads: List[tuple] = []
    thirds: List[tuple] = []
    positive = 0
    for day, xs in _by_date(records).items():
        xs = [x for x in xs if score(x) is not None and x.get("excess") is not None]
        if len(xs) < MIN_NAMES_PER_DATE:
            continue
        ic = spearman([float(score(x)) for x in xs], [x["excess"] for x in xs])
        if ic is not None:
            ics.append((day, ic))
            positive += ic > 0
        bull = [x["excess"] for x in xs if x["side"] > 0]
        bear = [x["excess"] for x in xs if x["side"] < 0]
        if bull and bear:
            spreads.append((day, mean(bull) - mean(bear)))
        ordered = sorted(xs, key=lambda x: float(score(x)))
        k = len(ordered) // 3
        if k:
            thirds.append((day, mean([x["excess"] for x in ordered[-k:]])
                           - mean([x["excess"] for x in ordered[:k]])))
    out = {"rank_ic": _series_stats(ics, horizon),
           "share_of_dates_positive": r(positive / len(ics), 3) if ics else None,
           "bull_minus_bear_excess_pct": _series_stats(spreads, horizon),
           "top_minus_bottom_third_excess_pct": _series_stats(thirds, horizon)}
    return out


def _hit_rate(records: Sequence[Dict[str, Any]], fn, horizon: int) -> Dict[str, Any]:
    """`rate` is the share of calls (what a reader means by a hit rate); the
    t-stat tests the per-date rates against 50%, because calls on one day are
    one draw of the market."""
    hits, points = [], []
    for day, xs in _by_date(records).items():
        hs = [h for h in map(fn, xs) if h is not None]
        if hs:
            hits += hs
            points.append((day, mean(hs) - 0.5))
    st = _series_stats(points, horizon)
    return {"rate": r(mean(hits), 3), "calls": len(hits), "t_vs_50pct": st["t"],
            "n_dates": st["n_dates"], "independent_windows": st["independent_windows"]}


def _abs_hit(x):
    return None if not x["side"] else float((x["raw"] > 0) if x["side"] > 0 else (x["raw"] < 0))


def _rel_hit(x):
    if not x["side"] or x.get("excess") is None:
        return None
    return float((x["excess"] > 0) if x["side"] > 0 else (x["excess"] < 0))


def direction(records: Sequence[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    by_action: Dict[str, Any] = {}
    for a in sorted({x["action"] for x in records}):
        xs = [x for x in records if x["action"] == a]
        ah = [h for h in map(_abs_hit, xs) if h is not None]
        rh = [h for h in map(_rel_hit, xs) if h is not None]
        ex = [x["excess"] for x in xs if x.get("excess") is not None]
        by_action[a] = {"n": len(xs), "hit_on_price": r(mean(ah), 3), "hit_vs_spy": r(mean(rh), 3),
                        "avg_return_pct": r(mean([x["raw"] for x in xs]), 2),
                        "avg_excess_pct": r(mean(ex), 2)}
    directional = [x for x in records if x["side"]]
    return {
        "directional_calls": len(directional),
        "hit_on_price": _hit_rate(directional, _abs_hit, horizon),
        "hit_vs_spy": _hit_rate(directional, _rel_hit, horizon),
        # The market's own share of up-moves over the same calls: the context
        # without which a hit rate on price cannot be read.
        "share_of_calls_where_stock_rose": r(mean([x["went_up"] for x in records]), 3),
        "share_of_calls_that_beat_spy": r(mean([x["beat"] for x in records
                                                if x.get("beat") is not None]), 3),
        "by_action": by_action,
    }


def _trailing_rate(records: Sequence[Dict[str, Any]], target: str):
    """For each call, the target's frequency among outcomes that had MATURED
    before that call was made — a baseline built only from what was known."""
    matured = sorted((x["outcome_date"], x[target]) for x in records
                     if x.get("outcome_date") and x.get(target) is not None)
    dates = [d for d, _ in matured]
    prefix = [0.0]
    for _, v in matured:
        prefix.append(prefix[-1] + v)

    def rate(call_date: str) -> Optional[float]:
        k = bisect.bisect_left(dates, call_date)
        return prefix[k] / k if k else None
    return rate


def probability(records: Sequence[Dict[str, Any]], horizon: int,
                prob: str = "p_up", target: str = "went_up") -> Dict[str, Any]:
    xs = [x for x in records if x.get(prob) is not None and x.get(target) is not None]
    if not xs:
        return {"n": 0}
    trailing = _trailing_rate(records, target)
    brier = mean([(x[prob] - x[target]) ** 2 for x in xs])
    b_half = 0.25                                    # always 50%: (0.5-o)^2
    with_trailing = [(x, trailing(x["call_date"])) for x in xs]
    with_trailing = [(x, t) for x, t in with_trailing if t is not None]
    b_trail = mean([(t - x[target]) ** 2 for x, t in with_trailing]) if with_trailing else None
    b_model_on_trail = mean([(x[prob] - x[target]) ** 2 for x, _ in with_trailing]) if with_trailing else None

    # Per-date improvement over the trailing base rate: positive = the stated
    # probability beat the no-skill baseline that day.
    daily: Dict[str, List[float]] = defaultdict(list)
    for x, t in with_trailing:
        daily[x["call_date"]].append((t - x[target]) ** 2 - (x[prob] - x[target]) ** 2)
    improvement = [(d, mean(v)) for d, v in sorted(daily.items())]

    bins = []
    ece_num = 0.0
    for lo, hi in P_BINS:
        b = [x for x in xs if lo <= x[prob] < hi]
        if not b:
            continue
        stated, realised = mean([x[prob] for x in b]), mean([x[target] for x in b])
        bins.append({"range": [lo, min(hi, 1.0)], "n": len(b), "stated": r(stated, 3),
                     "realised": r(realised, 3)})
        ece_num += abs(stated - realised) * len(b)
    return {
        "n": len(xs),
        "brier": r(brier),
        "brier_always_50pct": b_half,
        "brier_trailing_base_rate": r(b_trail),
        "skill_vs_50pct": r(1 - brier / b_half),
        "skill_vs_trailing_base_rate": (r(1 - b_model_on_trail / b_trail)
                                        if b_trail and b_model_on_trail is not None else None),
        "improvement_vs_trailing_by_date": _series_stats(improvement, horizon),
        "mean_stated": r(mean([x[prob] for x in xs]), 3),
        "mean_realised": r(mean([x[target] for x in xs]), 3),
        "reliability": bins,
        "ece": r(ece_num / len(xs)),
    }


def confidence(records: Sequence[Dict[str, Any]], horizon: int) -> List[Dict[str, Any]]:
    """What each label claimed when it was frozen against what it delivered.

    `claimed` is the number the record carried at the time (0.5 + 0.5 x the
    statistical-edge score), not today's map — a label is judged by the promise
    it made, not by one it could have made."""
    out = []
    for lvl in CONF_LEVELS:
        xs = [x for x in records if x["conf"] == lvl and x["side"]]
        if not xs:
            continue
        claimed = [0.5 + 0.5 * float(x["edge_score"]) for x in xs if x.get("edge_score") is not None]
        on_price = [h for h in map(_abs_hit, xs) if h is not None]
        vs_spy = [h for h in map(_rel_hit, xs) if h is not None]
        c = mean(claimed)
        out.append({"level": lvl, "n": len(xs), "claimed": r(c, 3),
                    "hit_on_price": r(mean(on_price), 3), "hit_vs_spy": r(mean(vs_spy), 3),
                    "overclaim_pts": r(100 * (c - mean(on_price)), 1) if c is not None and on_price else None})
    return out


def pillars(records: Sequence[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    return {p: ranking(records, horizon, score=lambda x, p=p: x["pillars"].get(p))["rank_ic"]
            for p in PILLARS}


def trend(records: Sequence[Dict[str, Any]], horizon: int) -> List[Dict[str, Any]]:
    """By call week: is the desk getting better or worse?"""
    from datetime import date
    weeks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for x in records:
        try:
            y, w, _ = date.fromisoformat(x["call_date"]).isocalendar()
        except (TypeError, ValueError):
            continue
        weeks[f"{y}-W{w:02d}"].append(x)
    out = []
    for wk, xs in sorted(weeks.items()):
        rk = ranking(xs, horizon)
        directional = [x for x in xs if x["side"]]
        out.append({"week": wk, "calls": len(xs),
                    "rank_ic": rk["rank_ic"]["mean"],
                    "bull_minus_bear_excess_pct": rk["bull_minus_bear_excess_pct"]["mean"],
                    "hit_on_price": r(mean([h for h in map(_abs_hit, directional) if h is not None]), 3),
                    "hit_vs_spy": r(mean([h for h in map(_rel_hit, directional) if h is not None]), 3)})
    return out


# ── Champion vs challengers ───────────────────────────────────────────────

_PAIRED = {"EDGE": "COMPOSITE_BETTER", "PROMISING": "COMPOSITE_BETTER_UNCONFIRMED",
           "ADVERSE": "CHALLENGER_BETTER", "NO_EDGE": "NO_DIFFERENCE",
           "INSUFFICIENT": "INSUFFICIENT"}


def paired_verdict(series: Dict[str, Any]) -> Dict[str, Any]:
    """verdict() on composite-minus-challenger, held to the SAME bar in both
    directions. verdict() flags ADVERSE without the window requirement because
    an early warning about the desk is cheap; "a challenger is better" is a
    claim that could replace part of the desk, so it needs the 20 windows too."""
    v = verdict(series)
    name = _PAIRED[v["verdict"]]
    w = series.get("independent_windows") or 0
    if name == "CHALLENGER_BETTER" and w < MIN_WINDOWS:
        name = "CHALLENGER_BETTER_UNCONFIRMED"
        v = dict(v, why=f"{v['why']}, but only {w} independent windows (need {MIN_WINDOWS})")
    return {"verdict": name, "why": v["why"]}


def challenger_scorecard(records: Sequence[Dict[str, Any]], horizon: int,
                         shadow: Optional[Dict[str, Dict[str, float]]] = None) -> Dict[str, Any]:
    """Each challenger against the composite, PAIRED: on every date, both rank
    the same names (those that have both scores), and the difference of the
    two rank ICs is the observation. Same t and independent-window rules as
    everything else; ADVERSE on the difference means the challenger wins."""
    from .challengers import CHALLENGERS, DESCRIPTIONS, PILLAR_CHALLENGERS, pillar_scores
    shadow = shadow or {}
    out: Dict[str, Any] = {}
    for name in CHALLENGERS:
        if name in PILLAR_CHALLENGERS:
            def score(x, name=name):
                return pillar_scores(x["pillars"], x.get("composite"), x).get(name)
        else:
            def score(x, name=name):
                return (shadow.get(x.get("snapshot_id")) or {}).get(name)
        diffs, champ, chal = [], [], []
        for day, xs in _by_date(records).items():
            xs = [x for x in xs if x.get("composite") is not None and score(x) is not None
                  and x.get("excess") is not None]
            if len(xs) < MIN_NAMES_PER_DATE:
                continue
            ex = [x["excess"] for x in xs]
            a = spearman([x["composite"] for x in xs], ex)
            b = spearman([float(score(x)) for x in xs], ex)
            if a is None or b is None:
                continue
            champ.append((day, a))
            chal.append((day, b))
            diffs.append((day, a - b))
        d = _series_stats(diffs, horizon)
        v = paired_verdict(d)
        out[name] = {"description": DESCRIPTIONS.get(name, name),
                     "calls_scored": sum(1 for x in records if score(x) is not None),
                     "challenger_rank_ic": _series_stats(chal, horizon),
                     "composite_rank_ic_same_names": _series_stats(champ, horizon),
                     "composite_minus_challenger": d,
                     "verdict": v["verdict"], "why": v["why"]}
    return out


# ── Verdicts ──────────────────────────────────────────────────────────────

def verdict(series: Dict[str, Any]) -> Dict[str, Any]:
    """EDGE / PROMISING / NO_EDGE / ADVERSE / INSUFFICIENT for one across-date
    series, under the rules at the top of this module."""
    n, t, m = series.get("n_dates") or 0, series.get("t"), series.get("mean")
    windows = series.get("independent_windows") or 0
    if n < MIN_DATES or t is None or m is None:
        return {"verdict": "INSUFFICIENT",
                "why": f"{n} usable call dates (need {MIN_DATES})"}
    if t <= -T_SIGNIFICANT:
        return {"verdict": "ADVERSE", "why": f"t={t:+.2f}: reliably wrong-way"}
    if t >= T_SIGNIFICANT and windows >= MIN_WINDOWS:
        return {"verdict": "EDGE", "why": f"t={t:+.2f} over {windows} independent windows"}
    if t >= T_SIGNIFICANT:
        return {"verdict": "PROMISING",
                "why": (f"t={t:+.2f}, but only {windows} independent windows "
                        f"(need {MIN_WINDOWS}) — the dates overlap too much to confirm")}
    return {"verdict": "NO_EDGE", "why": f"t={t:+.2f}: not distinguishable from zero"}


def horizon_scorecard(records: Sequence[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    cov = coverage(records, horizon)
    rk = ranking(records, horizon)
    p_up = probability(records, horizon, "p_up", "went_up")
    p_beat = probability(records, horizon, "p_beat", "beat")
    return {
        "horizon_days": horizon,
        "coverage": cov,
        "ranking": rk,
        "direction": direction(records, horizon),
        "p_up": p_up,
        "p_beat_spy": p_beat,
        "confidence": confidence(records, horizon),
        "pillars": pillars(records, horizon),
        "trend": trend(records, horizon),
        "verdicts": {
            "ranking": verdict(rk["rank_ic"]),
            "long_short": verdict(rk["bull_minus_bear_excess_pct"]),
            "p_up": (verdict(p_up["improvement_vs_trailing_by_date"])
                     if p_up.get("n") else {"verdict": "INSUFFICIENT", "why": "no stated p_up has matured"}),
            "p_beat_spy": (verdict(p_beat["improvement_vs_trailing_by_date"])
                           if p_beat.get("n") else
                           {"verdict": "INSUFFICIENT", "why": "no frozen P(beat SPY) has matured yet"}),
        },
    }
