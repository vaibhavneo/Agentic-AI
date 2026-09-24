"""
The gate. A proposal is REFUSED unless it can survive all of this.

A self-improving system that tunes itself on its own outcome history is, by
default, a machine for overfitting. Everything here exists to make that
default hard to reach, and the bar is deliberately set where a proposal that
cannot clear it is not promoted rather than promoted with a caveat.

Five checks, in the order they run, cheapest and most decisive first:

  1. SURFACE     the change is a declared tunable, inside bounds, inside
                 max_step, and the group's invariant still holds.
  2. EVIDENCE    enough INDEPENDENT windows, not enough rows. Overlapping
                 evaluation windows are the single easiest way to manufacture
                 significance from a ledger this size.
  3. SPLIT       train and test are split by TIME with a purge gap of one full
                 horizon. A random split leaks: rows adjacent in time share a
                 price path, so a shuffled fold tests on what it trained on.
  4. EFFECT      the candidate must beat the incumbent on HELD-OUT data by
                 more than MIN_EFFECT. Any two configurations differ by
                 something; a difference smaller than the noise floor is not
                 an improvement.
  5. STABILITY   the candidate must not lose on any individual held-out fold
                 by more than MAX_FOLD_REGRESSION. A candidate that wins on
                 average by winning enormously once and losing steadily is
                 fitting one episode.

The metric is the correlation between the weighted composite tilt and the
realized excess return, signed from the call's point of view. It is the right
target because it is exactly what a weight change alters — the ordering the
composite imposes — and it does not require simulating an execution policy,
which would smuggle in assumptions the ledger cannot support.

What this file will NOT do: lower a threshold because nothing is passing.
On the ledger as of 2026-09 almost nothing passes, and the correct response
is to keep accumulating evidence, not to move the bar to meet the data.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import surface as S
from .graph import PILLAR, graphs_for

# Minimum independent evaluation windows before ANY promotion is considered.
# Matched to intelligence.calibration.MIN_EFFECTIVE_OBS on purpose: a weight
# change is at least as consequential as a probability recalibration, so it
# must not clear a laxer bar than one.
MIN_EFFECTIVE_N = 20

# Rows needed regardless of independence — effective_n can be flattered by a
# long calendar span with few calls in it.
MIN_ROWS = 60

# Fraction of the (time-ordered) history held out.
TEST_FRACTION = 0.30

# Minimum improvement in the held-out metric to count as a real effect.
MIN_EFFECT = 0.02

# The most a candidate may lose on any single held-out fold and still pass.
MAX_FOLD_REGRESSION = 0.05

N_FOLDS = 3

# Verdicts
PROMOTE = "PROMOTE"
REFUSE = "REFUSE"


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            / math.sqrt(sxx * syy))


def composite_tilt(graph: Dict[str, Any], weights: Dict[str, float]) -> Optional[float]:
    """The decision's net lean under a given weighting.

    Read from the graph's pillar EDGES rather than recomputed from scores, so
    the candidate and the incumbent are scored over identically the same
    population — including the neutral-tilt exclusions.
    """
    num = 0.0
    seen = False
    for e in graph.get("edges") or []:
        if e.get("kind") != PILLAR or e.get("tilt") is None:
            continue
        w = float(weights.get(e["name"], 0.0))
        if w <= 0:
            continue
        num += float(e["tilt"]) * w
        seen = True
    return num if seen else None


def metric(graphs: Sequence[Dict[str, Any]], weights: Dict[str, float]
           ) -> Optional[float]:
    """Correlation of composite tilt with realized outcome, on one population."""
    xs, ys = [], []
    for g in graphs:
        c = composite_tilt(g, weights)
        if c is None or g.get("realized") is None:
            continue
        xs.append(c)
        ys.append(float(g["realized"]))
    return _pearson(xs, ys)


def _purged_time_split(graphs: Sequence[Dict[str, Any]], horizon: int,
                       n_folds: int = N_FOLDS) -> List[Tuple[List, List]]:
    """Forward-chaining folds cut on the CALENDAR, each purged by one horizon.

    Train is always strictly EARLIER than test — a model that may see the
    future is not being validated. The purge gap exists because a call made on
    the last training day is still resolving `horizon` days into the test
    window, so without it the two sets share a price path.

    Cutting on distinct DATES rather than on row index is load-bearing for
    this ledger specifically. Its calls are wildly uneven in time: 65 distinct
    dates spanning 2022-2026, but most rows sit in a two-week burst at the
    end. Splitting at quartiles of the ROW count put all three boundaries
    inside that burst, so an 8-day purge erased every test set and the gate
    refused for a reason that was an artifact of the split rather than a fact
    about the evidence. Cutting on dates makes each fold a real stretch of
    history, which is what a forward-chaining split is supposed to mean.
    """
    import datetime as dt

    def _d(g):
        try:
            return dt.date.fromisoformat((g.get("as_of") or "")[:10])
        except (ValueError, TypeError):
            return None

    dated = [(d, g) for g, d in ((g, _d(g)) for g in graphs) if d is not None]
    if len(dated) < MIN_ROWS:
        return []
    dated.sort(key=lambda p: p[0])
    dates = sorted({d for d, _ in dated})
    if len(dates) < n_folds + 2:
        return []

    # Horizon is in trading days; the purge must be in calendar days.
    purge = dt.timedelta(days=int(horizon * 365.0 / 252.0) + 1)

    folds: List[Tuple[List, List]] = []
    nd = len(dates)
    for k in range(n_folds):
        cut_i = int(nd * (k + 1) / (n_folds + 1))
        end_i = int(nd * (k + 2) / (n_folds + 1))
        if cut_i < 1 or end_i <= cut_i:
            continue
        boundary = dates[cut_i - 1]
        test_end = dates[end_i - 1]
        train = [g for d, g in dated if d <= boundary]
        test = [g for d, g in dated
                if boundary < d <= test_end and d - boundary >= purge]
        if len(train) >= 10 and len(test) >= 10:
            folds.append((train, test))
    return folds


def evaluate(group: str, current: Dict[str, float], candidate: Dict[str, float],
             horizon: int, graphs: Optional[Sequence[Dict[str, Any]]] = None
             ) -> Dict[str, Any]:
    """Run the full gate. Returns a verdict with every check's own result.

    The shape is deliberately uniform whether it passes or fails: a refusal
    that cannot be read as easily as an acceptance is a refusal nobody audits.
    """
    checks: List[Dict[str, Any]] = []

    def _add(name, ok, detail):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        return ok

    result: Dict[str, Any] = {
        "group": group, "horizon_days": horizon,
        "current": dict(current), "candidate": dict(candidate),
        "verdict": REFUSE, "checks": checks,
        "metric_current": None, "metric_candidate": None,
        "effect": None, "folds": [],
    }

    # ── 1. surface ────────────────────────────────────────────────────────
    surface_ok = True
    for key, new in candidate.items():
        ok, why = S.check_change(group, key, float(current.get(key, 0.0)), float(new))
        if not ok:
            surface_ok = _add("surface", False, why)
            break
    if surface_ok:
        ok, why = S.check_invariant(group, candidate)
        surface_ok = _add("surface", ok, why)
    if not surface_ok:
        result["reason"] = checks[-1]["detail"]
        return result

    # ── 2. evidence ───────────────────────────────────────────────────────
    if graphs is None:
        graphs = graphs_for(horizon)
    usable = [g for g in graphs if g.get("realized") is not None and g.get("as_of")]

    from intelligence.calibration import effective_sample_size
    eff = effective_sample_size([g["as_of"] for g in usable], horizon)
    result["n_rows"] = len(usable)
    result["effective_n"] = eff

    if not _add("evidence_rows", len(usable) >= MIN_ROWS,
                f"{len(usable)} attributable rows, need {MIN_ROWS}"):
        result["reason"] = checks[-1]["detail"]
        return result
    if not _add("evidence_independent", eff >= MIN_EFFECTIVE_N,
                f"{eff} independent {horizon}-day windows, need {MIN_EFFECTIVE_N}"
                + ("" if eff >= MIN_EFFECTIVE_N else
                   f" — {len(usable)} rows overlap in time, so row count "
                   f"overstates the evidence by {len(usable) / max(eff, 1):.0f}x")):
        result["reason"] = checks[-1]["detail"]
        return result

    # ── 3. split ──────────────────────────────────────────────────────────
    folds = _purged_time_split(usable, horizon)
    if not _add("purged_split", bool(folds),
                f"{len(folds)} usable purged forward-chaining folds"
                if folds else
                "no fold survived purging — every test window is inside one "
                "horizon of its training data, so none can be tested "
                "independently"):
        result["reason"] = checks[-1]["detail"]
        return result

    # ── 4. effect, out of sample ──────────────────────────────────────────
    deltas: List[float] = []
    for i, (_train, test) in enumerate(folds):
        m_cur = metric(test, current)
        m_cand = metric(test, candidate)
        row = {"fold": i, "n_test": len(test),
               "metric_current": (round(m_cur, 5) if m_cur is not None else None),
               "metric_candidate": (round(m_cand, 5) if m_cand is not None else None)}
        if m_cur is not None and m_cand is not None:
            row["delta"] = round(m_cand - m_cur, 5)
            deltas.append(m_cand - m_cur)
        result["folds"].append(row)

    if not _add("measurable", len(deltas) == len(folds) and bool(deltas),
                f"{len(deltas)} of {len(folds)} folds produced a comparable "
                f"metric on both configurations"):
        result["reason"] = checks[-1]["detail"]
        return result

    effect = sum(deltas) / len(deltas)
    result["metric_current"] = round(
        sum(f["metric_current"] for f in result["folds"]) / len(deltas), 5)
    result["metric_candidate"] = round(
        sum(f["metric_candidate"] for f in result["folds"]) / len(deltas), 5)
    result["effect"] = round(effect, 5)

    if not _add("effect", effect >= MIN_EFFECT,
                f"held-out improvement {effect:+.5f}, need at least "
                f"{MIN_EFFECT:+.5f}"):
        result["reason"] = checks[-1]["detail"]
        return result

    # ── 5. stability ──────────────────────────────────────────────────────
    worst = min(deltas)
    if not _add("stability", worst >= -MAX_FOLD_REGRESSION,
                f"worst fold moved {worst:+.5f}, floor is "
                f"{-MAX_FOLD_REGRESSION:+.5f}"):
        result["reason"] = checks[-1]["detail"]
        return result

    result["verdict"] = PROMOTE
    result["reason"] = (f"improved the held-out metric by {effect:+.5f} across "
                        f"{len(deltas)} purged folds with no fold worse than "
                        f"{worst:+.5f}, on {eff} independent windows")
    return result


# ── confidence map: a different question needs a different metric ──────────
#
# The composite-tilt correlation above measures an ORDERING, which is what a
# weight change alters. A confidence map changes no ordering at all — it
# restates the probability attached to an unchanged call. Scoring it with the
# tilt metric would report an effect of exactly zero for every candidate and
# refuse them all for a reason that has nothing to do with whether the
# candidate is better.
#
# The right metric is the Brier score: mean squared error between the stated
# probability and what happened. Lower is better, so the effect is the
# REDUCTION, and the sign convention is inverted relative to `evaluate`.

def _level_of(snapshot: Dict[str, Any]) -> str:
    from .graph import _decision_confidence
    return _decision_confidence(snapshot)


def brier_under(rows: Sequence[Dict[str, Any]], mapping: Dict[str, float]
                ) -> Optional[float]:
    """Mean Brier of a set of resolved calls under a stated-probability map."""
    terms = []
    for r in rows:
        p = mapping.get(r["level"])
        if p is None:
            continue
        terms.append((float(p) - (1.0 if r["won"] else 0.0)) ** 2)
    return (sum(terms) / len(terms)) if terms else None


def _confidence_rows(horizon: int) -> List[Dict[str, Any]]:
    """Resolved calls reduced to (date, confidence level, won)."""
    from .graph import ACTION_DIRECTION, load_resolved

    out: List[Dict[str, Any]] = []
    for snap, outcome in load_resolved(horizon):
        direction = ACTION_DIRECTION.get(str(snap.get("action") or "").upper())
        if not direction:
            continue                       # HOLD expresses no view to score
        excess = outcome.get("excess_return_pct")
        if excess is None:
            continue
        level = _level_of(snap)
        if level == "NONE":
            continue
        out.append({"as_of": (snap.get("created_at") or "")[:10],
                    "level": level,
                    "won": (float(excess) * direction) > 0})
    return out


def evaluate_confidence(current: Dict[str, float], candidate: Dict[str, float],
                        horizon: int,
                        rows: Optional[Sequence[Dict[str, Any]]] = None
                        ) -> Dict[str, Any]:
    """The gate for CONFIDENCE_MAP. Same five checks, Brier as the metric."""
    checks: List[Dict[str, Any]] = []

    def _add(name, ok, detail):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        return ok

    result: Dict[str, Any] = {
        "group": S.CONFIDENCE_MAP, "horizon_days": horizon,
        "current": dict(current), "candidate": dict(candidate),
        "verdict": REFUSE, "checks": checks, "metric_name": "brier (lower is better)",
        "metric_current": None, "metric_candidate": None,
        "effect": None, "folds": [],
    }

    for key, new in candidate.items():
        ok, why = S.check_change(S.CONFIDENCE_MAP, key,
                                 float(current.get(key, 0.0)), float(new))
        if not ok:
            _add("surface", False, why)
            result["reason"] = why
            return result
    ok, why = S.check_invariant(S.CONFIDENCE_MAP, candidate)
    if not _add("surface", ok, why):
        result["reason"] = why
        return result

    if rows is None:
        rows = _confidence_rows(horizon)
    rows = [r for r in rows if r.get("as_of")]
    result["n_rows"] = len(rows)

    from intelligence.calibration import effective_sample_size
    eff = effective_sample_size([r["as_of"] for r in rows], horizon)
    result["effective_n"] = eff

    if not _add("evidence_rows", len(rows) >= MIN_ROWS,
                f"{len(rows)} resolved calls with a confidence level, "
                f"need {MIN_ROWS}"):
        result["reason"] = checks[-1]["detail"]
        return result
    if not _add("evidence_independent", eff >= MIN_EFFECTIVE_N,
                f"{eff} independent {horizon}-day windows, need "
                f"{MIN_EFFECTIVE_N}"):
        result["reason"] = checks[-1]["detail"]
        return result

    folds = _purged_time_split(rows, horizon)
    if not _add("purged_split", bool(folds),
                f"{len(folds)} usable purged folds" if folds else
                "no fold survived purging"):
        result["reason"] = checks[-1]["detail"]
        return result

    deltas: List[float] = []
    for i, (_train, test) in enumerate(folds):
        b_cur = brier_under(test, current)
        b_cand = brier_under(test, candidate)
        row = {"fold": i, "n_test": len(test),
               "metric_current": (round(b_cur, 5) if b_cur is not None else None),
               "metric_candidate": (round(b_cand, 5) if b_cand is not None else None)}
        if b_cur is not None and b_cand is not None:
            # Brier is an error: the improvement is the REDUCTION.
            row["delta"] = round(b_cur - b_cand, 5)
            deltas.append(b_cur - b_cand)
        result["folds"].append(row)

    if not _add("measurable", len(deltas) == len(folds) and bool(deltas),
                f"{len(deltas)} of {len(folds)} folds scored on both maps"):
        result["reason"] = checks[-1]["detail"]
        return result

    effect = sum(deltas) / len(deltas)
    result["metric_current"] = round(
        sum(f["metric_current"] for f in result["folds"]) / len(deltas), 5)
    result["metric_candidate"] = round(
        sum(f["metric_candidate"] for f in result["folds"]) / len(deltas), 5)
    result["effect"] = round(effect, 5)

    if not _add("effect", effect >= MIN_EFFECT,
                f"held-out Brier fell by {effect:+.5f}, need at least "
                f"{MIN_EFFECT:+.5f}"):
        result["reason"] = checks[-1]["detail"]
        return result

    worst = min(deltas)
    if not _add("stability", worst >= -MAX_FOLD_REGRESSION,
                f"worst fold moved {worst:+.5f}, floor is "
                f"{-MAX_FOLD_REGRESSION:+.5f}"):
        result["reason"] = checks[-1]["detail"]
        return result

    result["verdict"] = PROMOTE
    result["reason"] = (f"reduced held-out Brier by {effect:+.5f} across "
                        f"{len(deltas)} purged folds, on {eff} independent windows")
    return result


def evaluate_any(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Route a proposal to the gate that can actually score it."""
    group = proposal.get("group")
    horizon = int(proposal.get("horizon_days") or 0)
    cur = proposal.get("current") or {}
    cand = proposal.get("candidate") or {}
    if group == S.CONFIDENCE_MAP:
        return evaluate_confidence(cur, cand, horizon)
    return evaluate(group, cur, cand, horizon)


# ── what is even reachable ─────────────────────────────────────────────────
#
# The independence bar has a consequence worth stating out loud rather than
# rediscovering every cycle: you cannot observe N non-overlapping H-day
# windows in less than N*H days of history, no matter how many calls you make.
# Sampling more names on more days raises the row count and does not move
# `effective_sample_size`, because its SPAN ceiling is a fact about the
# calendar.
#
# At MIN_EFFECTIVE_N = 20 that means a 20-day horizon needs about 1.6 years of
# history, a 1-year horizon needs 20 years, and a 3-year horizon needs 60.
# Multi-year tuning is therefore not "waiting for more data" — it is out of
# reach of this method, and a loop that keeps emitting "3 of 20 independent
# windows" forever implies a patience that will never be rewarded.
#
# The honest response is to say which horizons are reachable, when, and which
# are not reachable at all. Lowering the bar for long horizons would be the
# dishonest alternative: it would let the system tune multi-year behaviour on
# three overlapping observations.

CALENDAR_PER_TRADING_DAY = 365.0 / 252.0


def years_required(horizon: int, min_windows: int = MIN_EFFECTIVE_N) -> float:
    """Calendar years of history needed for `min_windows` independent windows."""
    return (min_windows * horizon * CALENDAR_PER_TRADING_DAY) / 365.0


def feasibility(horizon: int, dates: Optional[Sequence[str]] = None
                ) -> Dict[str, Any]:
    """Can this horizon ever clear the bar, and if so when?"""
    import datetime as dt

    if dates is None:
        dates = [g["as_of"] for g in graphs_for(horizon) if g.get("as_of")]
    clean = sorted({str(d)[:10] for d in dates if d})

    span_years = 0.0
    if len(clean) >= 2:
        try:
            d0 = dt.date.fromisoformat(clean[0])
            d1 = dt.date.fromisoformat(clean[-1])
            span_years = (d1 - d0).days / 365.0
        except ValueError:
            span_years = 0.0

    need = years_required(horizon)
    from intelligence.calibration import effective_sample_size
    eff = effective_sample_size(clean, horizon) if clean else 0
    shortfall = max(0.0, need - span_years)

    # A horizon whose requirement exceeds a working career of market history
    # is not a scheduling problem.
    out_of_reach = need > 25.0

    if eff >= MIN_EFFECTIVE_N:
        state, statement = "REACHABLE_NOW", (
            f"{horizon}-day tuning has {eff} independent windows and can be "
            f"evaluated now.")
    elif out_of_reach:
        state, statement = "OUT_OF_REACH", (
            f"{horizon}-day tuning would need about {need:.0f} years of history "
            f"for {MIN_EFFECTIVE_N} independent windows, and {span_years:.1f} "
            f"years exist. This is a limit of the method, not a backlog: "
            f"non-overlapping {horizon}-day windows accumulate at one per "
            f"{horizon * CALENDAR_PER_TRADING_DAY / 365.0:.1f} years however "
            f"many calls are made, so no amount of sampling shortens it. This "
            f"horizon is tracked and reported, never tuned.")
    else:
        state, statement = "REACHABLE_LATER", (
            f"{horizon}-day tuning needs about {need:.1f} years of history and "
            f"has {span_years:.1f}. Roughly {shortfall:.1f} more years — or a "
            f"point-in-time replay extending the history backwards, which "
            f"produces the same independent windows without waiting.")

    return {"horizon_days": horizon, "state": state,
            "effective_n": eff, "required_windows": MIN_EFFECTIVE_N,
            "history_years": round(span_years, 2),
            "years_required": round(need, 2),
            "shortfall_years": round(shortfall, 2),
            "statement": statement}
