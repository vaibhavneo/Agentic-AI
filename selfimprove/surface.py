"""
The TUNABLE SURFACE — the bounded, declared set of things the self-improvement
loop is permitted to change.

This module is the safety boundary of the whole package, and it is a
whitelist rather than a blacklist on purpose. A loop that can edit arbitrary
parameters is a loop that can quietly turn the system into something nobody
designed and nobody reviewed; a loop that can only move declared knobs inside
declared bounds can at worst make a reviewable, reversible mistake.

Four properties every tunable declares, and the loop enforces all four before
a proposal is even considered:

  bounds     hard floor and ceiling. A proposal outside them is rejected
             without being evaluated, so no amount of apparent evidence can
             argue the weights to somewhere absurd.
  max_step   the most any single promotion may move the value. Evidence
             accumulates slowly; a knob that can jump the full range in one
             cycle converts a single lucky quarter into a regime change.
  invariant  a named constraint the whole group must satisfy after the change
             (pillar weights must still sum to 1).
  rationale  why this knob is tunable at all, in terms of a MEASUREMENT. A
             knob nobody can justify from evidence does not belong here.

Deliberately NOT tunable, and each for a reason:

  action band thresholds — they define what BUY means. A loop that moves them
      changes the meaning of past records, so the track record stops being
      comparable to itself and calibration silently measures two things.
  the asset-class specs — days_per_year and the volatility bands are facts
      about a market, not preferences. 365 for crypto is not a hyperparameter.
  evidence tier ranks — tier dominance is a designed epistemic rule. Letting
      outcomes argue a prose claim up to the rank of a measurement is how a
      system talks itself into trusting narrative.
  anything in the risk veto — a safety limit that optimises itself against
      recent returns is not a safety limit.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ── invariants ────────────────────────────────────────────────────────────
SUM_TO_ONE = "sum_to_one"
MONOTONIC_INCREASING = "monotonic_increasing"

PILLAR_WEIGHTS = "pillar_weights"
CONFIDENCE_MAP = "confidence_map"
ALGO_LEG_WEIGHTS = "algo_leg_weights"

# A group whose invariant is MONOTONIC_INCREASING needs its SEMANTIC order
# declared. Sorting the keys alphabetically puts HIGH before LOW, which would
# reject the correct map (LOW .5, MEDIUM .6, HIGH .7) as an inversion and
# accept a genuinely inverted one. The ordering is a fact about the labels,
# so it is declared rather than derived.
GROUP_ORDER: Dict[str, Tuple[str, ...]] = {
    CONFIDENCE_MAP: ("LOW", "MEDIUM", "HIGH"),
}


class Tunable:
    """One knob. Immutable declaration; the VALUES live in the active config."""

    __slots__ = ("group", "key", "lo", "hi", "max_step", "invariant",
                 "rationale", "horizon_scoped")

    def __init__(self, group: str, key: str, lo: float, hi: float,
                 max_step: float, rationale: str,
                 invariant: Optional[str] = None,
                 horizon_scoped: bool = False):
        self.group = group
        self.key = key
        self.lo = lo
        self.hi = hi
        self.max_step = max_step
        self.invariant = invariant
        self.rationale = rationale
        self.horizon_scoped = horizon_scoped

    def clamp(self, v: float) -> float:
        return max(self.lo, min(self.hi, float(v)))

    def in_bounds(self, v: float) -> bool:
        return self.lo <= float(v) <= self.hi

    def step_ok(self, old: float, new: float) -> bool:
        return abs(float(new) - float(old)) <= self.max_step + 1e-9

    def as_dict(self) -> Dict[str, Any]:
        return {"group": self.group, "key": self.key, "bounds": [self.lo, self.hi],
                "max_step": self.max_step, "invariant": self.invariant,
                "rationale": self.rationale, "horizon_scoped": self.horizon_scoped}


# The three core pillars carry CORE_WEIGHTS in backtest/pillars.py. Their
# measured information coefficient against forward return differs by horizon
# (fundamentals strengthens with horizon, technical decays and turns negative),
# while the weights are one horizon-invariant constant. That mismatch is the
# measurement this knob exists to let the system act on.
_PILLAR_RATIONALE = (
    "CORE_WEIGHTS is horizon-invariant while the pillars' measured correlation "
    "with forward return is horizon-dependent: on the ledger as of 2026-09, "
    "fundamentals runs +0.097 / +0.175 / +0.214 at 5 / 20 / 60 days while "
    "technical runs +0.043 / -0.039 / -0.111. Weighting the same way at every "
    "horizon is the thing the evidence contradicts.")

# A floor above zero matters: a pillar driven to 0 stops being scored, stops
# generating outcome rows, and can therefore never earn its weight back. The
# floor keeps every pillar observable so the loop stays able to change its mind.
PILLAR_FLOOR = 0.05
PILLAR_CEILING = 0.70
PILLAR_MAX_STEP = 0.05

_CONFIDENCE_RATIONALE = (
    "confidence_reliability on the ledger as of 2026-09 shows MEDIUM claiming "
    "a 0.877 win probability and realising 0.533, and LOW claiming 0.717 and "
    "realising 0.507 — gaps of 34 and 21 points. The label is a promise the "
    "record does not keep, and this knob is the promise.")

TUNABLES: Dict[Tuple[str, str], Tunable] = {}


def _register(t: Tunable) -> Tunable:
    TUNABLES[(t.group, t.key)] = t
    return t


for _p in ("technical", "algo", "fundamentals"):
    _register(Tunable(PILLAR_WEIGHTS, _p, PILLAR_FLOOR, PILLAR_CEILING,
                      PILLAR_MAX_STEP, _PILLAR_RATIONALE,
                      invariant=SUM_TO_ONE, horizon_scoped=True))

# The algo pillar is four voting legs, and until the decomposition landed only
# their blend was recorded, so nothing could ask which leg carried a decision.
# Measured over 49,880 daily observations across 20 large caps and 11 calendar
# years: momentum and mean reversion had OPPOSITE-signed 20-day IC in 7 of the
# 11 years (momentum +0.164 in 2016 against mean reversion -0.106; momentum
# -0.098 in 2019 against mean reversion +0.070). Voting them at equal weight is
# close to a guarantee of cancellation, and the blend's IC of about +0.005 at 20
# days is that cancellation. The trend leg was negative at 5 and 60 days and the
# volume leg fired on 5.8% of bars with no consistent sign.
#
# None of which is an edge — every candidate reweighting tested negative out of
# sample. It is a reason these four should be weighed SEPARATELY on their own
# records instead of pre-blended into one number nobody could attribute.
_ALGO_LEG_RATIONALE = (
    "The four algo legs were pre-blended at fixed vote weights (2/2/1/2) and "
    "only the blend was recorded. Measured separately over 49,880 daily "
    "observations, momentum and mean reversion carried opposite-signed 20-day "
    "IC in 7 of 11 calendar years, so equal weights cancel them; the trend leg "
    "measured negative at 5 and 60 days and the volume leg fired on 5.8% of "
    "bars. Each leg should answer for itself.")

# A leg floor of ZERO, unlike the pillar floor. The reasoning that keeps a
# pillar above zero does not apply here: a pillar at zero weight stops being
# scored and stops generating attributable observations, so it can never earn
# its weight back. A leg's VOTE is computed from prices regardless of what it
# is weighted, so a retired leg stays fully measurable and the loop can always
# change its mind. Retirement is therefore safe here and is the point.
ALGO_LEG_FLOOR = 0.0
ALGO_LEG_CEILING = 4.0
ALGO_LEG_MAX_STEP = 0.5

for _leg in ("mean_reversion", "momentum", "trend", "volume"):
    _register(Tunable(ALGO_LEG_WEIGHTS, _leg, ALGO_LEG_FLOOR, ALGO_LEG_CEILING,
                      ALGO_LEG_MAX_STEP, _ALGO_LEG_RATIONALE,
                      invariant=None, horizon_scoped=True))

for _lvl in ("LOW", "MEDIUM", "HIGH"):
    _register(Tunable(CONFIDENCE_MAP, _lvl, 0.35, 0.95, 0.10,
                      _CONFIDENCE_RATIONALE, invariant=MONOTONIC_INCREASING,
                      horizon_scoped=True))


def get(group: str, key: str) -> Optional[Tunable]:
    return TUNABLES.get((group, key))


def is_tunable(group: str, key: str) -> bool:
    return (group, key) in TUNABLES


def groups() -> List[str]:
    return sorted({g for g, _ in TUNABLES})


def keys_in(group: str) -> List[str]:
    """Declared keys in SEMANTIC order where the group declares one, else
    alphabetical. Order is load-bearing for MONOTONIC_INCREASING."""
    present = {k for g, k in TUNABLES if g == group}
    declared = GROUP_ORDER.get(group)
    if declared:
        ordered = [k for k in declared if k in present]
        return ordered + sorted(present - set(ordered))
    return sorted(present)


def check_invariant(group: str, values: Dict[str, float]) -> Tuple[bool, str]:
    """Validate a whole group AFTER a proposed change. Per-key bounds are not
    enough: three individually legal weights can still fail to sum to 1, and a
    confidence map can invert so that LOW promises more than HIGH."""
    inv = None
    for k in values:
        t = get(group, k)
        if t is not None and t.invariant:
            inv = t.invariant
            break

    for k, v in values.items():
        t = get(group, k)
        if t is None:
            return False, f"{group}.{k} is not a declared tunable"
        if not t.in_bounds(v):
            return False, (f"{group}.{k}={v:.4f} is outside its bounds "
                           f"[{t.lo}, {t.hi}]")

    if inv == SUM_TO_ONE:
        declared = set(keys_in(group))
        if set(values) != declared:
            missing = declared - set(values)
            extra = set(values) - declared
            return False, (f"{group} must set every key to check {SUM_TO_ONE}; "
                           f"missing={sorted(missing)} unexpected={sorted(extra)}")
        total = sum(float(v) for v in values.values())
        if abs(total - 1.0) > 1e-6:
            return False, f"{group} weights sum to {total:.6f}, not 1.0"

    if inv == MONOTONIC_INCREASING:
        order = keys_in(group)
        present = [(k, float(values[k])) for k in order if k in values]
        for (ka, va), (kb, vb) in zip(present, present[1:]):
            if vb < va:
                return False, (f"{group} must not invert: {ka}={va:.3f} "
                               f"exceeds {kb}={vb:.3f}")

    return True, "ok"


def check_change(group: str, key: str, old: float, new: float) -> Tuple[bool, str]:
    """Validate one key's movement: declared, in bounds, and inside max_step."""
    t = get(group, key)
    if t is None:
        return False, (f"{group}.{key} is not a declared tunable; the loop may "
                       f"only move knobs on the declared surface")
    if not t.in_bounds(new):
        return False, (f"{group}.{key}={new:.4f} is outside its bounds "
                       f"[{t.lo}, {t.hi}]")
    if not t.step_ok(old, new):
        return False, (f"{group}.{key} would move {abs(new - old):.4f} in one "
                       f"promotion, beyond max_step {t.max_step}")
    return True, "ok"


def describe() -> List[Dict[str, Any]]:
    """The whole surface, for the API and the audit trail. A reader must be
    able to see everything the loop can touch without reading the code."""
    return [TUNABLES[k].as_dict() for k in sorted(TUNABLES)]
