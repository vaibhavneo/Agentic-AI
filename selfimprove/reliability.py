"""
What a confidence label has actually been worth — attached to the label.

The measurement that motivated this module: on the ledger as of 2026-09, a
MEDIUM-confidence 20-day call stated an implied win probability of 0.877 and
realised 0.533, and LOW stated 0.717 and realised 0.507. Gaps of 34 and 21
points, with ECE 0.26. The badge was a promise the record did not keep, and
nothing anywhere in the system said so.

Two separate things are reported, and keeping them apart is the point:

  CALIBRATED   the probability the self-improvement loop has validated for this
               label and horizon, out of sample. This is what the label SHOULD
               promise. It only exists once the loop has promoted a change for
               that horizon, so its absence is informative rather than an error.

  REALISED     the frequency this label has actually achieved, straight from
               `calibration_report`'s confidence_reliability. This is a
               measurement, not a parameter, and it is reported whether or not
               the loop has acted on it.

Why this module exists rather than the loop's config being read directly: the
config is the loop's own state, and a caller that read it would be quoting a
number with no sample size next to it. A stated probability without the count
behind it is exactly the kind of claim this whole exercise is about removing.

`describe()` returns None when there is nothing measured to say. A caller
should render nothing in that case, never a reassuring default — a badge with
no record behind it should look like a badge with no record behind it.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import config as C
from . import surface as S

# Below this the realised rate is noise with a decimal point, and quoting it
# beside a confidence badge would replace one unfounded number with another.
MIN_N_TO_QUOTE = 30


def calibrated(level: str, horizon: int) -> Optional[float]:
    """The loop's validated probability for this label, if it has one."""
    lvl = (level or "").upper()
    live = C.active(S.CONFIDENCE_MAP, horizon)
    base = C.defaults(S.CONFIDENCE_MAP)
    if lvl not in live:
        return None
    # Only report it as calibrated if it actually differs from the shipped
    # default — otherwise this would dress an untouched constant up as a
    # validated measurement.
    if abs(float(live[lvl]) - float(base.get(lvl, live[lvl]))) <= 1e-9:
        return None
    return float(live[lvl])


def realized(level: str, horizon: int) -> Optional[Dict[str, Any]]:
    """The measured record for this label at this horizon.

    The horizon is resolved to one the LEDGER actually evaluates. The desk
    decides at 45, 91 or 126 days, and the ledger grades at 1/5/20/60/126/252 —
    so asking it about 91 returns an empty report and the badge went bare for
    almost every real decision. Same resolution the weights use, so a decision's
    weights and its track record always come from the same horizon.
    """
    lvl = (level or "").upper()
    from .config import resolve_horizon
    resolved, _note = resolve_horizon(horizon)
    if resolved is None:
        return None
    try:
        from data.prediction_ledger import calibration_report
        rep = calibration_report(horizon=resolved, source="all")
    except Exception:
        return None
    for row in (rep.get("confidence_reliability") or []):
        if str(row.get("level") or "").upper() != lvl:
            continue
        n = int(row.get("n") or 0)
        if n < MIN_N_TO_QUOTE:
            return None
        return {"n": n,
                "realized_win_rate": row.get("realized_win_rate"),
                "stated_win_prob": row.get("predicted_win_prob"),
                "gap": row.get("calibration_gap"),
                "horizon_days": resolved,
                "asked_horizon_days": int(horizon)}
    return None


def describe(level: str, horizon: int) -> Optional[Dict[str, Any]]:
    """One label's track record, ready to render beside it. None if silent."""
    lvl = (level or "").upper()
    rec = realized(lvl, horizon)
    cal = calibrated(lvl, horizon)
    if not rec and cal is None:
        return None

    out: Dict[str, Any] = {"level": lvl, "horizon_days": horizon,
                           "calibrated_win_prob": cal, "record": rec}

    if rec and rec.get("realized_win_rate") is not None:
        rate = float(rec["realized_win_rate"])
        measured_at = rec.get("horizon_days", horizon)
        at = (f"{measured_at} days" if measured_at == int(horizon)
              else f"{measured_at} days (nearest graded to this {horizon}-day call)")
        parts = [f"{lvl} confidence at {at} has won "
                 f"{rate * 100:.0f}% of {rec['n']} resolved calls"]
        stated = rec.get("stated_win_prob")
        if stated is not None and rec.get("gap") is not None \
                and float(rec["gap"]) >= 0.05:
            parts.append(f"against an implied {float(stated) * 100:.0f}%, a gap "
                         f"of {float(rec['gap']) * 100:.0f} points")
        if cal is not None:
            parts.append(f"the loop has since validated {cal * 100:.0f}% as the "
                         f"stated figure")
        out["statement"] = "; ".join(parts) + "."
    else:
        out["statement"] = (
            f"{lvl} confidence at {horizon} days carries a loop-validated "
            f"{cal * 100:.0f}% stated probability, on too few resolved calls to "
            f"quote a frequency yet.")
    return out


def annotate(decomposed: Dict[str, Any], horizon: int) -> Dict[str, Any]:
    """Attach the headline confidence's record to a decomposed confidence dict.

    Returns the same dict with a `track_record` key when there is something
    measured to say, and unchanged when there is not. Non-mutating on the
    caller's own structure is deliberate: this is an annotation, and a
    confidence decomposition that silently changed shape depending on how much
    history existed would be harder to consume, not easier.
    """
    headline = (decomposed or {}).get("decision_confidence")
    if not headline:
        return decomposed
    try:
        rec = describe(str(headline), int(horizon))
    except Exception:
        return decomposed
    if not rec:
        return decomposed
    out = dict(decomposed)
    out["track_record"] = rec
    out["summary"] = f"{out.get('summary', '')} — {rec['statement']}".strip(" —")
    return out
