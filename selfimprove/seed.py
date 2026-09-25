"""
Carrying learned parameters to a deployment that cannot do the learning.

There is exactly ONE canonical evidence ledger (see prediction_ledger.
ledger_role). Every other deployment quarantines its own snapshots at write
time so two partial histories can never disagree about what the system
predicted. That invariant is right, and it has a consequence for this package:

  the self-improvement loop can only LEARN where the canonical ledger is.

Running it on a secondary deployment is not harmful — it reads an evidence
population of zero and refuses every proposal — but it is inert, and a loop
that looks alive while learning nothing is exactly the failure this whole
effort exists to remove.

So learning and serving are separated, which is the ordinary shape for this:
train where the data is, deploy the trained parameters. The canonical machine
exports what it has validated into `learned_config.json`, that file is
committed, and every deployment reads it as a layer between the shipped
defaults and its own local overrides:

    shipped defaults  <  committed seed  <  local DB override

A secondary deployment has no local overrides, so it serves the seed. The
canonical machine's own DB always wins over the seed, so exporting then
re-reading is not circular.

The seed is committed rather than pushed through an environment variable on
purpose: it is a set of numbers that change what every prediction scores, and
it belongs in review and in history like any other change to behaviour.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any, Dict, Optional

from . import surface as S

SEED_PATH = pathlib.Path(__file__).parent / "learned_config.json"

_cache: Optional[Dict[str, Any]] = None


def export(path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    """Write the canonical machine's validated overrides to the seed file.

    Refuses to run anywhere but the canonical ledger. A secondary deployment
    exporting its (empty, or worse, partially-learned) state would overwrite
    the real thing with nothing.
    """
    from data.prediction_ledger import is_canonical_ledger, ledger_role
    if not is_canonical_ledger():
        return {"written": False,
                "reason": (f"this deployment's LEDGER_ROLE is "
                           f"{ledger_role()!r}; only the canonical ledger may "
                           f"export a seed, because only it learned from a "
                           f"complete evidence population")}

    from . import config as C
    from . import ledger as L

    groups: Dict[str, Any] = {}
    for row in C.overrides():
        grp, horizon, key = row["grp"], str(row["horizon_days"]), row["key"]
        if not S.is_tunable(grp, key):
            continue        # never carry a knob the surface no longer declares
        groups.setdefault(grp, {}).setdefault(horizon, {})[key] = float(row["value"])

    # Validate every group/horizon before writing. A seed that fails its own
    # invariant would be loaded by production and rejected there, silently
    # leaving it on defaults with no indication why.
    rejected = []
    for grp, horizons in list(groups.items()):
        for horizon, values in list(horizons.items()):
            ok, why = S.check_invariant(grp, values)
            if not ok:
                rejected.append({"group": grp, "horizon_days": horizon,
                                 "reason": why})
                del horizons[horizon]
        if not horizons:
            del groups[grp]

    payload = {
        "_comment": ("Parameters the self-improvement loop validated on the "
                     "CANONICAL ledger, carried to deployments that cannot "
                     "learn because their own snapshots are quarantined. "
                     "Written by selfimprove.seed.export(); read as a layer "
                     "between the shipped defaults and any local override. "
                     "Delete this file to return every deployment to the "
                     "weights the code ships with."),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "surface_keys": {g: S.keys_in(g) for g in S.groups()},
        "groups": groups,
        "provenance": L.summary(),
    }
    target = path or SEED_PATH
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    global _cache
    _cache = None
    return {"written": True, "path": str(target), "groups": groups,
            "rejected": rejected}


def load() -> Dict[str, Any]:
    """The seed's groups, or {} when there is no seed. Cached; never raises."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = json.loads(SEED_PATH.read_text())
        groups = raw.get("groups") or {}
        if not isinstance(groups, dict):
            groups = {}
    except (OSError, ValueError):
        groups = {}
    _cache = groups
    return groups


def applies_here() -> bool:
    """The seed is for deployments that CANNOT learn, and only those.

    The canonical ledger must ignore it entirely. It has the full evidence
    population, so it learns from the shipped defaults upward; reading its own
    exported seed as a baseline would make every comparison circular — the
    review step would re-test a learned value against itself and find no
    effect, and the cooldown would read a seeded value as a promotion already
    in force.
    """
    try:
        from data.prediction_ledger import is_canonical_ledger
        return not is_canonical_ledger()
    except Exception:
        # Unknown role: behave like the canonical machine and ignore the seed.
        # The failure that matters is a deployment silently scoring on numbers
        # nobody can trace, and ignoring the seed cannot cause that.
        return False


def for_group(group: str, horizon: int) -> Dict[str, float]:
    """Seeded values for one group/horizon, validated. {} if absent or invalid.

    Re-validated on READ as well as on write. The file is committed, so it can
    be hand-edited, and a seed that violates an invariant must not reach a
    score — silently ignoring it and staying on the shipped defaults is the
    safe failure.
    """
    if not applies_here():
        return {}
    groups = load()
    horizons = groups.get(group) or {}
    values = horizons.get(str(int(horizon))) or {}
    if not values:
        return {}
    clean = {k: float(v) for k, v in values.items() if S.is_tunable(group, k)}
    if not clean:
        return {}
    ok, _why = S.check_invariant(group, clean)
    return clean if ok else {}


def describe() -> Dict[str, Any]:
    """What this deployment is serving from the seed, for the status endpoint."""
    groups = load()
    if groups and not applies_here():
        return {"seeded": False, "seed_present": True,
                "statement": ("A learned-parameter seed exists but is ignored "
                              "here: this is the canonical ledger, which learns "
                              "from the shipped defaults upward. Reading its "
                              "own export would make every comparison "
                              "circular.")}
    if not groups:
        return {"seeded": False,
                "statement": ("No learned-parameter seed is present, so every "
                              "tunable runs on the weights the code ships "
                              "with unless this deployment learned its own.")}
    n = sum(len(h) for h in groups.values())
    return {"seeded": True, "groups": groups, "n_group_horizons": n,
            "statement": (f"Serving {n} learned group/horizon parameter set"
                          f"{'s' if n != 1 else ''} from the committed seed, "
                          f"validated on the canonical ledger. A local "
                          f"override, where one exists, takes precedence.")}
