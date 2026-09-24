"""
The cycle. Propose, verify, record, apply — and, just as importantly, review.

A loop that can only adopt changes is a ratchet, not a learning system. It
accumulates whatever cleared the bar on the evidence available that week and
has no way to notice when later evidence stops supporting it. So a cycle has
two halves:

  ADVANCE   for each horizon and each tunable group, ask the proposer for a
            candidate, put it through the gate, record the verdict, and apply
            it if it passed.

  REVIEW    for each override already active, re-run the gate on TODAY's
            evidence. If the change that justified it no longer clears the
            bar, roll it back.

Review runs FIRST. An override that no longer holds is already affecting
every prediction the system makes, so removing it is more urgent than adding
anything new, and reviewing afterwards would evaluate new proposals against a
configuration already known to be stale.

The loop never touches anything outside `surface.py`, never places an order,
and never widens its own thresholds. Its single most common outcome, on the
evidence this ledger currently holds, is to refuse — and the refusals are
recorded with the same care as the promotions, because the refusal rate is
the honest measure of how much the system actually knows.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from . import config as C
from . import ledger as L
from . import propose as P
from . import surface as S
from .verify import PROMOTE, evaluate, evaluate_any, evaluate_confidence

# Horizons the loop tunes. 1-day is excluded deliberately: at a one-day
# horizon the outcome is dominated by microstructure and overnight gaps that
# none of the pillars claim to forecast, so fitting weights to it would tune
# the system on the one horizon its signals are not about.
HORIZONS = (5, 20, 60, 126, 252, 504)


def _evaluate_active(group: str, horizon: int) -> Dict[str, Any]:
    """Re-run the gate on an ACTIVE override, comparing it to the defaults.

    The comparison is against `defaults`, not against the override itself —
    the question under review is the original one ("is this better than stock
    behaviour"), re-asked on more evidence. Comparing an override to itself
    would be vacuous.
    """
    base = C.defaults(group)
    live = C.active(group, horizon)
    if group == S.CONFIDENCE_MAP:
        return evaluate_confidence(base, live, horizon)
    return evaluate(group, base, live, horizon)


def review(cycle_id: str, dry_run: bool = False) -> List[Dict[str, Any]]:
    """Re-test every active override; roll back the ones that no longer hold."""
    out: List[Dict[str, Any]] = []
    seen = {(o["grp"], o["horizon_days"]) for o in C.overrides()}
    for group, horizon in sorted(seen):
        if horizon == C.ALL_HORIZONS:
            continue
        try:
            ev = _evaluate_active(group, horizon)
        except Exception as e:
            out.append({"group": group, "horizon_days": horizon,
                        "action": "error", "detail": f"{type(e).__name__}: {e}"})
            continue

        still_holds = ev.get("verdict") == PROMOTE
        entry = {"group": group, "horizon_days": horizon,
                 "still_holds": still_holds, "reason": ev.get("reason"),
                 "effect": ev.get("effect"), "action": "kept"}

        if not still_holds:
            entry["action"] = "would_roll_back" if dry_run else "rolled_back"
            if not dry_run:
                # A re-test that no longer passes is itself a decision, and it
                # goes into the append-only record before the config moves, so
                # the reason survives even if the write fails.
                pid = L.record({**ev, "verdict": "ROLLBACK"}, cycle_id=cycle_id)
                C.revert(group, horizon, proposal_id=pid)
                if pid:
                    L.mark_rolled_back(pid)
                entry["proposal_id"] = pid
        out.append(entry)
    return out


def advance(cycle_id: str, dry_run: bool = False,
            horizons: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """Generate, gate, record and (unless dry) apply one round of proposals."""
    out: List[Dict[str, Any]] = []
    for horizon in (horizons or HORIZONS):
        for proposal in P.all_for(horizon):
            try:
                ev = evaluate_any(proposal)
            except Exception as e:
                out.append({"group": proposal.get("group"),
                            "horizon_days": horizon, "verdict": "ERROR",
                            "reason": f"{type(e).__name__}: {e}"})
                continue

            promoted = ev.get("verdict") == PROMOTE
            applied = False
            pid = L.record(ev, cycle_id=cycle_id, applied=False)

            if promoted and not dry_run:
                res = C.apply(proposal["group"], horizon,
                              proposal["candidate"], proposal_id=pid)
                applied = bool(res.get("applied"))
                if applied and pid:
                    L.mark_applied(pid)

            out.append({
                "proposal_id": pid,
                "group": proposal.get("group"),
                "horizon_days": horizon,
                "verdict": ev.get("verdict"),
                "reason": ev.get("reason"),
                "effect": ev.get("effect"),
                "effective_n": ev.get("effective_n"),
                "argument": proposal.get("argument"),
                "current": proposal.get("current"),
                "candidate": proposal.get("candidate"),
                "applied": applied,
                "would_apply": promoted and dry_run,
            })
    return out


def cycle(dry_run: bool = False,
          horizons: Optional[List[int]] = None) -> Dict[str, Any]:
    """One full pass. Safe to call on a schedule; never raises."""
    cycle_id = uuid.uuid4().hex[:12]
    t0 = time.time()
    reviewed = review(cycle_id, dry_run=dry_run)
    advanced = advance(cycle_id, dry_run=dry_run, horizons=horizons)

    promoted = [a for a in advanced if a.get("verdict") == PROMOTE]
    refused = [a for a in advanced if a.get("verdict") not in (PROMOTE, "ERROR")]
    rolled = [r for r in reviewed if r.get("action") in
              ("rolled_back", "would_roll_back")]

    return {
        "cycle_id": cycle_id,
        "dry_run": dry_run,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "reviewed": reviewed,
        "advanced": advanced,
        "n_proposed": len(advanced),
        "n_promoted": len(promoted),
        "n_refused": len(refused),
        "n_rolled_back": len(rolled),
        "statement": _statement(advanced, reviewed, dry_run),
    }


def _statement(advanced: List[Dict[str, Any]], reviewed: List[Dict[str, Any]],
               dry_run: bool) -> str:
    n = len(advanced)
    promoted = [a for a in advanced if a.get("verdict") == PROMOTE]
    rolled = [r for r in reviewed if r.get("action") in
              ("rolled_back", "would_roll_back")]
    if not n and not reviewed:
        return ("No proposal was generated and nothing is overridden: every "
                "proposer found the evidence too thin or too evenly balanced "
                "to argue for a change.")

    verb = "would be" if dry_run else "was"
    parts = [f"{n} proposal{'s' if n != 1 else ''} evaluated, "
             f"{len(promoted)} {verb} promoted"]
    if rolled:
        parts.append(f"{len(rolled)} active override"
                     f"{'s' if len(rolled) != 1 else ''} no longer held and "
                     f"{verb} rolled back")
    refusals = [a for a in advanced if a.get("verdict") not in (PROMOTE, "ERROR")]
    if refusals:
        thin = sum(1 for a in refusals
                   if "independent" in (a.get("reason") or ""))
        small = sum(1 for a in refusals
                    if "need at least" in (a.get("reason") or ""))
        detail = []
        if thin:
            detail.append(f"{thin} for too few independent windows")
        if small:
            detail.append(f"{small} for an effect inside the noise floor")
        if detail:
            parts.append("refused " + " and ".join(detail))
    return "; ".join(parts) + "."


def status() -> Dict[str, Any]:
    """What the loop has done and what is live because of it."""
    active: List[Dict[str, Any]] = []
    for group in S.groups():
        for horizon in HORIZONS:
            base, live = C.defaults(group), C.active(group, horizon)
            diff = {k: [base.get(k), live.get(k)] for k in live
                    if abs(float(live[k]) - float(base.get(k, live[k]))) > 1e-9}
            if diff:
                active.append({"group": group, "horizon_days": horizon,
                               "changed": diff})
    from .verify import feasibility
    reach = []
    for horizon in HORIZONS:
        try:
            reach.append(feasibility(horizon))
        except Exception:
            continue
    now = [f for f in reach if f["state"] == "REACHABLE_NOW"]
    never = [f for f in reach if f["state"] == "OUT_OF_REACH"]

    return {
        "surface": S.describe(),
        "active_overrides": active,
        "n_active_overrides": len(active),
        "ledger": L.summary(),
        "horizons": list(HORIZONS),
        # Which horizons this method can ever tune, and when. Without it the
        # long horizons emit the same "3 of 20 independent windows" refusal
        # every cycle forever, implying a patience that will never be
        # rewarded — a 1-year horizon needs 20 years of history to reach 20
        # non-overlapping windows, and no amount of extra sampling shortens
        # that, because the ceiling is the calendar.
        "feasibility": reach,
        "statement": (
            f"{len(active)} tunable group/horizon pair"
            f"{'s are' if len(active) != 1 else ' is'} currently overridden by "
            f"the loop; everything else runs on the defaults the code ships "
            f"with. {len(now)} of {len(reach)} horizons have enough independent "
            f"history to tune today"
            + (f"; {len(never)} cannot be reached by this method at all and "
               f"{'are' if len(never) != 1 else 'is'} tracked but never tuned."
               if never else ".")),
    }
