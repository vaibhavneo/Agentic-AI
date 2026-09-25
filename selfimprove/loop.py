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
    # check_step=False: the live config may legitimately sit several bounded
    # steps from the defaults, and max_step governs how fast the loop moves a
    # knob rather than which positions may exist. Re-testing with the step
    # check on would roll back correctly-reached positions for a reason that
    # has nothing to do with whether they still work.
    if group == S.CONFIDENCE_MAP:
        return evaluate_confidence(base, live, horizon, check_step=False)
    return evaluate(group, base, live, horizon, check_step=False)


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
                # Mark the ORIGINAL promotion as rolled back, not the rollback
                # record just written. Marking the new row leaves the original
                # looking live, so `last_promotion` keeps finding it and holds
                # the knob in cooldown forever -- stuck at defaults AND unable
                # to re-earn the change.
                original = L.last_promotion(group, horizon)
                if original:
                    L.mark_rolled_back(original["proposal_id"])
                entry["proposal_id"] = pid
                entry["rolled_back_promotion"] = (
                    original["proposal_id"] if original else None)
        out.append(entry)
    return out


# A knob may not step again until the EVIDENCE has grown by this many
# independent windows since the promotion that last moved it.
#
# Without it the cycle re-derives the same conclusion from the same data every
# six hours and takes another bounded step each time, walking the weights to
# their bounds on the strength of a single measurement. Bounds and max_step
# cap the damage but do not prevent it: twelve cycles a day reach any bound
# inside a week.
#
# Independent windows, not wall-clock time, because that is what actually
# changes what is knowable. At a 20-day horizon genuinely new evidence arrives
# every 20 trading days however often the loop runs, and gating on the clock
# would let a fast schedule outrun the data again.
MIN_NEW_WINDOWS_TO_STEP_AGAIN = 3


def _evidence_has_grown(group: str, horizon: int,
                        current_effective_n: Optional[int]) -> tuple:
    """May this knob move again yet?"""
    prior = L.last_promotion(group, horizon)
    if not prior:
        return True, "no prior promotion for this knob"

    # The ledger and the config can disagree: a promotion recorded as live
    # while the knob actually sits at its defaults means the change is not in
    # force, whatever the record says. Gating on a promotion that is not
    # actually applied strands the knob permanently -- reverted AND barred
    # from re-earning the change. Trust the config, which is what predictions
    # actually read, and let the record be corrected by the next rollback.
    live = C.active(group, horizon)
    base = C.defaults(group)
    if all(abs(float(live.get(k, v)) - float(v)) <= 1e-9
           for k, v in base.items()):
        return True, ("the last recorded promotion is not reflected in the "
                      "active config, so nothing is in force to wait on")
    before = prior.get("effective_n")
    if before is None or current_effective_n is None:
        return True, "prior promotion recorded no sample size to compare"
    grown = int(current_effective_n) - int(before)
    if grown >= MIN_NEW_WINDOWS_TO_STEP_AGAIN:
        return True, (f"{grown} new independent windows since the last "
                      f"promotion moved this knob")
    return False, (f"only {grown} new independent window"
                   f"{'s' if grown != 1 else ''} since the last promotion "
                   f"moved this knob (need {MIN_NEW_WINDOWS_TO_STEP_AGAIN}); "
                   f"stepping again would re-derive the same conclusion from "
                   f"the same evidence")


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
            if promoted:
                may_step, why = _evidence_has_grown(
                    proposal["group"], horizon, ev.get("effective_n"))
                if not may_step:
                    promoted = False
                    ev = {**ev, "verdict": "COOLDOWN", "reason": why}

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

    def _verb(count):
        if dry_run:
            return "would be"
        return "was" if count == 1 else "were"

    parts = [f"{n} proposal{'s' if n != 1 else ''} evaluated, "
             f"{len(promoted)} {_verb(len(promoted))} promoted"]
    if rolled:
        parts.append(f"{len(rolled)} active override"
                     f"{'s' if len(rolled) != 1 else ''} no longer held and "
                     f"{_verb(len(rolled))} rolled back")
    # COOLDOWN is counted apart from REFUSE. Both mention "independent
    # windows", and lumping them together reported a knob that had just been
    # promoted as though its evidence were too thin -- the opposite of why it
    # was held.
    cooled = [a for a in advanced if a.get("verdict") == "COOLDOWN"]
    refusals = [a for a in advanced
                if a.get("verdict") not in (PROMOTE, "ERROR", "COOLDOWN")]
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
    if cooled:
        parts.append(f"{len(cooled)} held in cooldown, already promoted on "
                     f"this evidence and waiting for more")
    return "; ".join(parts) + "."


def _seed_describe() -> Dict[str, Any]:
    try:
        from .seed import describe
        return describe()
    except Exception:
        return {"seeded": False, "statement": "the seed could not be read"}


def _ledger_role() -> Dict[str, Any]:
    """Whether this deployment can LEARN, as opposed to serve what was learned.

    A secondary deployment quarantines its own snapshots, so its evidence
    population is empty and the loop will correctly refuse everything forever.
    That is not a fault, but it must be stated: a loop running on a secondary
    deployment looks identical to one that is learning, and the difference
    matters entirely.
    """
    try:
        from data.prediction_ledger import is_canonical_ledger, ledger_role
        canonical = is_canonical_ledger()
        return {
            "role": ledger_role(),
            "can_learn": canonical,
            "statement": (
                "This is the canonical ledger: the loop learns here, and what "
                "it validates can be exported as a seed for other deployments."
                if canonical else
                "This is a SECONDARY ledger. Its own snapshots are quarantined "
                "so two partial histories cannot disagree, which means its "
                "evidence population is empty and the loop will refuse every "
                "proposal here however long it runs. It serves parameters "
                "learned on the canonical ledger instead; learning happens "
                "there."),
        }
    except Exception:
        return {"role": "unknown", "can_learn": False,
                "statement": "the ledger role could not be determined"}


def apply_mode() -> Dict[str, Any]:
    """Is the SCHEDULED loop armed to apply, or only to propose?

    Read from the environment the same way data.maintenance.self_improve reads
    it, so this reports the running process's actual behaviour rather than a
    separate opinion about it. A loop whose arming cannot be observed is one
    nobody can tell is working.
    """
    import os
    raw = os.getenv("SELFIMPROVE_APPLY", "")
    armed = raw.strip().lower() in ("1", "true", "yes", "on")
    return {
        "armed": armed,
        "env_var": "SELFIMPROVE_APPLY",
        "env_value": raw or None,
        "statement": (
            "The scheduled loop is ARMED: a proposal that clears the gate is "
            "applied, and the change is recorded and reversible."
            if armed else
            "The scheduled loop is DRY: it attributes, proposes, verifies and "
            "records every verdict, but moves nothing. Set SELFIMPROVE_APPLY=1 "
            "to let it act."),
    }


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
        "apply_mode": apply_mode(),
        "learned_seed": _seed_describe(),
        "ledger_role": _ledger_role(),
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
