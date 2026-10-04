"""
P(beat the benchmark) — the composite's measured ranking skill, stated as a
probability and held to the same out-of-sample bar as p_up's calibration.

Why this exists. Graded against the ledger in 2026-10, the desk's calls were a
coin flip on DIRECTION (50% at 1d, 49% at 5d) while the composite RANKED the
same day's names against SPY with positive skill (per-date rank IC about +0.08
at 1d and +0.12 at 5d). Direction is mostly the market; ranking is the engine.
p_up states the first and nothing stated the second, so the part that worked
was never written down as a claim that could be graded.

The model is an isotonic map: composite score (0-100) -> frequency with which
calls at that score beat the benchmark over the horizon. It is monotone, so it
can never reorder names — it only says how much a score has been worth.

Gate (all must hold, or the horizon states nothing):
  * at least MIN_CALIBRATION_OBS graded rows with a frozen composite;
  * at least MIN_EFFECTIVE_OBS independent windows (the calibration layer's
    effective_sample_size — the bar is shared, never lowered here);
  * time-blocked, purged CV Brier of the map beats predicting the training
    rows' base rate. Beating the base rate is the point: a map that only
    learns "most names lagged SPY this quarter" has learned the regime, not
    the engine, and is refused.

Frozen at the call (outperform_probabilities on the snapshot) and graded
against excess_return > 0 by evaluation/. Never frozen by replay: a map fitted
on today's ledger stamped onto a 2019 call would be look-ahead.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from intelligence.calibration import (MIN_CALIBRATION_OBS, MIN_EFFECTIVE_OBS,
                                      apply_isotonic, fit_isotonic,
                                      purged_cv_brier)

_CACHE_TTL_S = 600.0
_cache: Dict[Tuple[Tuple[int, ...], str], Tuple[float, Dict[int, Dict[str, Any]]]] = {}


def pairs_for_horizon(horizon: int, source: str = "all") -> List[Tuple[float, float, str]]:
    """(composite at the call, beat the benchmark?, outcome date)."""
    from data import prediction_ledger as pl

    conn = pl._conn()
    try:
        rows = conn.execute(
            f"""SELECT json_extract(s.frozen_json, '$.composite') AS composite,
                       o.excess_return_pct, o.as_of_date, s.created_at
                  FROM prediction_outcomes o
                  JOIN prediction_snapshots s ON s.snapshot_id = o.snapshot_id
                 WHERE o.horizon_days=? AND o.matured=1
                       AND o.excess_return_pct IS NOT NULL
                       AND json_extract(s.frozen_json, '$.composite') IS NOT NULL
                       {pl._source_where(source)}""",
            (horizon,)).fetchall()
    finally:
        conn.close()
    return [(float(r["composite"]), 1.0 if float(r["excess_return_pct"]) > 0 else 0.0,
             str(r["as_of_date"] or r["created_at"] or "")[:10]) for r in rows]


def fit_from_pairs(pairs: Sequence[Tuple[float, float, str]], horizon: int,
                   min_obs: int = MIN_CALIBRATION_OBS) -> Dict[str, Any]:
    """Fit and grade one horizon's map. Never raises; `applied` is the gate."""
    result: Dict[str, Any] = {"horizon_days": horizon, "applied": False,
                              "n": len(pairs), "map": None, "reason": None}
    if len(pairs) < min_obs:
        result["reason"] = f"insufficient_outcomes ({len(pairs)}<{min_obs})"
        return result
    cv = purged_cv_brier(pairs, horizon, baseline="base_rate")
    if not cv:
        result["reason"] = "cv_unavailable"
        return result
    result["brier_base_rate"] = round(cv["brier_raw"], 5)
    result["brier_model"] = round(cv["brier_calibrated"], 5)
    result["effective_n"] = cv["effective_n"]
    result["base_rate"] = round(sum(o for _, o, _ in pairs) / len(pairs), 4)
    if cv["effective_n"] < MIN_EFFECTIVE_OBS:
        result["reason"] = (f"insufficient_independent_windows "
                            f"({cv['effective_n']}<{MIN_EFFECTIVE_OBS})")
        return result
    if cv["brier_calibrated"] >= cv["brier_raw"]:
        result["reason"] = "no_out_of_sample_skill_vs_base_rate"
        return result
    cal_map = fit_isotonic([(c, o) for c, o, _ in pairs])
    if not cal_map:
        result["reason"] = "fit_failed"
        return result
    result["map"] = cal_map
    result["applied"] = True
    result["brier_skill"] = round(1.0 - cv["brier_calibrated"] / cv["brier_raw"], 4)
    return result


def fit_outperform(horizon: int, source: str = "all") -> Dict[str, Any]:
    try:
        pairs = pairs_for_horizon(horizon, source)
    except Exception as e:
        return {"horizon_days": horizon, "applied": False, "n": 0, "map": None,
                "reason": f"ledger_unavailable: {str(e)[:80]}"}
    return fit_from_pairs(pairs, horizon)


def load_models(horizons: Sequence[int], source: str = "all",
                use_cache: bool = True) -> Dict[int, Dict[str, Any]]:
    """fit_outperform() per horizon, cached briefly — the web path asks on every
    analysis and the answer only changes when outcomes are graded."""
    key = (tuple(int(h) for h in horizons), source)
    now = time.time()
    if use_cache and key in _cache and now - _cache[key][0] < _CACHE_TTL_S:
        return _cache[key][1]
    models = {int(h): fit_outperform(int(h), source) for h in horizons}
    _cache[key] = (now, models)
    return models


def clear_cache() -> None:
    _cache.clear()


def probabilities(composite: Optional[float],
                  models: Optional[Dict[int, Dict[str, Any]]]) -> Optional[Dict[int, float]]:
    """{horizon: P(beat benchmark)} for the horizons whose map earned its place;
    None when no horizon qualifies or there is no composite. Absence is the
    honest answer, not 0.5."""
    if composite is None or not models:
        return None
    out = {int(h): round(max(0.02, min(0.98, apply_isotonic(float(composite), m["map"]))), 3)
           for h, m in models.items() if m.get("applied") and m.get("map")}
    return out or None


def status(models: Dict[int, Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """The models without their knot arrays — what a report or API shows."""
    return {int(h): {k: v for k, v in m.items() if k != "map"} for h, m in models.items()}
