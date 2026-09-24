"""
Candidate generation — turning a scorecard into a specific proposed change.

Proposing is separated from verifying so that the thing making suggestions can
never be the thing approving them. A single function that both invented and
accepted a change would have no natural place to say no.

Proposals are deliberately SMALL and SINGLE-DIRECTION. Each one moves weight
from the worst-evidenced pillar to the best-evidenced one by at most max_step,
rather than jumping to whatever weighting maximises the in-sample metric. The
optimum-seeking version is strictly worse here: with the ledger's effective
sample size, the argmax of an in-sample objective is mostly a description of
which fold got lucky, and it would clear the effect gate by fitting the very
data the gate re-tests it on.

The confidence proposer is a different animal and worth distinguishing. It is
not an optimisation at all — it is a MEASUREMENT being copied into a promise.
When MEDIUM claims 0.877 and realises 0.533, proposing 0.533 is not a guess
about what works better; it is the stated probability being made to match the
observed frequency. It still goes through the same gate, because a realised
rate on thin evidence is itself uncertain.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config as C
from . import surface as S
from .scorecard import build as build_scorecards
from .graph import PILLAR

# A pillar needs at least this many attributable observations before its IC is
# allowed to argue for a weight change. Below it the correlation is noise with
# a decimal point.
MIN_OBS_FOR_PILLAR = 30

# Two pillars whose ICs differ by less than this are treated as tied, and no
# proposal is made. Without it the loop proposes a change every cycle on the
# strength of the fourth decimal place and churns the weights forever.
IC_TIE_BAND = 0.03


def _renormalize(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {k: v / total for k, v in weights.items()}


def pillar_weights(horizon: int,
                   current: Optional[Dict[str, float]] = None
                   ) -> Optional[Dict[str, Any]]:
    """Propose a one-step reweighting for one horizon, or None.

    Returning None is the common and correct outcome. A proposer that always
    has something to suggest guarantees the gate is the only thing standing
    between the system and constant churn.
    """
    cur = dict(current if current is not None else C.active(S.PILLAR_WEIGHTS, horizon))
    tunable_keys = set(S.keys_in(S.PILLAR_WEIGHTS))
    cards = build_scorecards(horizon)

    ranked: List[Dict[str, Any]] = []
    for node, card in cards.items():
        kind, _, name = node.partition(":")
        if kind != PILLAR or name not in tunable_keys:
            continue
        if (card.get("n") or 0) < MIN_OBS_FOR_PILLAR or card.get("ic") is None:
            continue
        ranked.append({"pillar": name, "ic": float(card["ic"]),
                       "n": card["n"], "effective_n": card["effective_n"]})

    if len(ranked) < 2:
        return None

    ranked.sort(key=lambda r: r["ic"])
    worst, best = ranked[0], ranked[-1]
    if best["ic"] - worst["ic"] < IC_TIE_BAND:
        return None

    t_from = S.get(S.PILLAR_WEIGHTS, worst["pillar"])
    t_to = S.get(S.PILLAR_WEIGHTS, best["pillar"])
    if t_from is None or t_to is None:
        return None

    # The step is bounded three ways at once: by max_step, by how much the
    # donor can give before hitting its floor, and by how much the recipient
    # can take before hitting its ceiling. The floor is why a pillar can never
    # be driven to zero and stranded there unable to earn its weight back.
    step = min(t_from.max_step, t_to.max_step,
               cur.get(worst["pillar"], 0.0) - t_from.lo,
               t_to.hi - cur.get(best["pillar"], 0.0))
    if step <= 1e-6:
        return None

    candidate = dict(cur)
    candidate[worst["pillar"]] = cur[worst["pillar"]] - step
    candidate[best["pillar"]] = cur[best["pillar"]] + step
    candidate = {k: round(v, 6) for k, v in _renormalize(candidate).items()}

    return {
        "group": S.PILLAR_WEIGHTS, "horizon_days": horizon,
        "current": cur, "candidate": candidate,
        "argument": (
            f"At {horizon} days, {best['pillar']} has the strongest measured "
            f"relationship to realised outcome (ic {best['ic']:+.4f} over "
            f"{best['n']} observations, {best['effective_n']} independent) and "
            f"{worst['pillar']} the weakest (ic {worst['ic']:+.4f} over "
            f"{worst['n']}). Moving {step:.3f} of weight from the second to "
            f"the first is the smallest change that acts on that."),
        "evidence": ranked,
    }


def confidence_map(horizon: int,
                   current: Optional[Dict[str, float]] = None
                   ) -> Optional[Dict[str, Any]]:
    """Propose the REALISED win rate as the stated win probability.

    Reads confidence_reliability from the prediction ledger, which already
    computes predicted-vs-realised per level. Nothing is optimised here: the
    proposal simply is the measurement.
    """
    from data.prediction_ledger import calibration_report

    cur = dict(current if current is not None
               else C.active(S.CONFIDENCE_MAP, horizon))
    try:
        rep = calibration_report(horizon=horizon, source="all")
    except Exception:
        return None

    rows = rep.get("confidence_reliability") or []
    observed = {}
    for r in rows:
        lvl = str(r.get("level") or "").upper()
        realized = r.get("realized_win_rate")
        n = r.get("n") or 0
        if lvl in cur and realized is not None and n >= MIN_OBS_FOR_PILLAR:
            observed[lvl] = float(realized)
    if not observed:
        return None

    candidate = dict(cur)
    moved = []
    for lvl, realized in observed.items():
        t = S.get(S.CONFIDENCE_MAP, lvl)
        if t is None:
            continue
        old = float(cur.get(lvl, realized))
        # Step toward the realised rate, never all the way in one cycle: a
        # realised rate on a thin sample is itself an estimate, and jumping
        # onto it would track sampling noise level by level.
        target = t.clamp(realized)
        delta = max(-t.max_step, min(t.max_step, target - old))
        if abs(delta) < 1e-6:
            continue
        candidate[lvl] = round(old + delta, 6)
        moved.append((lvl, old, realized, candidate[lvl]))

    if not moved:
        return None

    ok, why = S.check_invariant(S.CONFIDENCE_MAP, candidate)
    if not ok:
        # Stepping each level independently can transiently invert the map.
        # Refusing here is right: the proposer's job is to offer only
        # well-formed candidates, not to let the gate catch its arithmetic.
        return None

    detail = "; ".join(
        f"{lvl} promises {old:.3f} and realises {real:.3f}, stepping to {new:.3f}"
        for lvl, old, real, new in moved)
    return {
        "group": S.CONFIDENCE_MAP, "horizon_days": horizon,
        "current": cur, "candidate": candidate,
        "argument": (f"At {horizon} days the stated confidence does not match "
                     f"the record: {detail}. This copies the measurement into "
                     f"the promise rather than optimising anything."),
        "evidence": rows,
    }


PROPOSERS = {
    S.PILLAR_WEIGHTS: pillar_weights,
    S.CONFIDENCE_MAP: confidence_map,
}


def all_for(horizon: int) -> List[Dict[str, Any]]:
    """Every proposer's candidate for one horizon, skipping the silent ones."""
    out = []
    for group in sorted(PROPOSERS):
        try:
            p = PROPOSERS[group](horizon)
        except Exception:
            p = None
        if p:
            out.append(p)
    return out
