"""
Node scorecards — what the attribution graph adds up to.

One scorecard per (node, horizon). The horizon split is not a convenience:
the measurement that motivated this whole package is that the pillars'
relationship to forward return CHANGES with horizon while their weights do
not. Pooling horizons would average that finding away.

Every scorecard carries `effective_n` beside `n`, and downstream code is
expected to read the first. Two calls made a week apart and graded over the
following quarter share most of their price path; counting them as two
observations is how an overlapping ledger talks itself into significance.
`effective_n` comes from intelligence.calibration.effective_sample_size,
which is already the gate the calibration layer trusts — reusing it means a
proposal cannot clear a laxer bar than a calibration fit would.

`ic` here is a Pearson correlation between a node's tilt and the realized
excess return, from the CALL's point of view. It is deliberately not called
an information coefficient anywhere a reader might take it for the
cross-sectional, per-period IC of the factor literature: this is pooled
across names and dates, so it answers "did leaning this way tend to pay"
rather than "how well does this factor rank a cross-section".
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .graph import PILLAR, graphs_for, walk


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def _mean(vs: Sequence[float]) -> Optional[float]:
    return (sum(vs) / len(vs)) if vs else None


def score_node(observations: List[Dict[str, Any]],
               horizon: int) -> Dict[str, Any]:
    """One node's record at one horizon."""
    from intelligence.calibration import effective_sample_size

    obs = [o for o in observations if o.get("realized") is not None]
    n = len(obs)
    dates = [o.get("as_of") or "" for o in obs]
    eff = effective_sample_size(dates, horizon) if dates else 0

    realized = [float(o["realized"]) for o in obs]
    agreed = [1.0 for o in obs if o.get("agreed")]
    tilted = [o for o in obs if o.get("tilt") is not None]

    ic = None
    contrib_weighted = None
    if tilted:
        ic = _pearson([float(o["tilt"]) for o in tilted],
                      [float(o["realized"]) for o in tilted])
        # The return this node's contribution actually earned: its signed
        # share of the decision times what the decision made. This is the
        # number a reweighting changes, which a bare correlation is not.
        contrib_weighted = _mean([float(o["contribution"]) * float(o["realized"])
                                  for o in tilted
                                  if o.get("contribution") is not None])

    first = min(dates) if dates else None
    last = max(dates) if dates else None

    return {
        "horizon_days": horizon,
        "n": n,
        "effective_n": eff,
        "hit_rate": round(len(agreed) / n, 4) if n else None,
        "mean_realized_pct": round(_mean(realized), 4) if realized else None,
        "ic": round(ic, 4) if ic is not None else None,
        "contribution_weighted_pct": (round(contrib_weighted, 6)
                                      if contrib_weighted is not None else None),
        "mean_tilt": (round(_mean([float(o["tilt"]) for o in tilted]), 4)
                      if tilted else None),
        "mean_weight": (round(_mean([float(o["weight"]) for o in tilted]), 4)
                        if tilted else None),
        "first_call": first,
        "last_call": last,
        "n_distinct_dates": len({d for d in dates if d}),
    }


def build(horizon: int, weights: Optional[Dict[str, float]] = None,
          limit: int = 5000) -> Dict[str, Dict[str, Any]]:
    """Every node's scorecard at one horizon, keyed by node id."""
    by_node = walk(graphs_for(horizon, weights=weights, limit=limit))
    return {node: score_node(obs, horizon) for node, obs in by_node.items()}


def pillar_scorecards(horizons: Iterable[int],
                      weights: Optional[Dict[str, float]] = None
                      ) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Pillars only, pivoted pillar -> horizon -> scorecard.

    This is the shape the proposal engine reads, because a reweighting
    argument is inherently a comparison ACROSS horizons for one pillar.
    """
    out: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for h in horizons:
        cards = build(h, weights=weights)
        for node, card in cards.items():
            kind, _, name = node.partition(":")
            if kind != PILLAR:
                continue
            out.setdefault(name, {})[h] = card
    return out


def summarize(horizon: int, min_n: int = 5) -> List[Dict[str, Any]]:
    """Ranked, human-readable node table. Nodes below `min_n` are dropped —
    a node with two observations has a hit rate of 0, 50 or 100 percent and
    ranking on it would put noise at the top of the list."""
    cards = build(horizon)
    rows = []
    for node, c in cards.items():
        if (c.get("n") or 0) < min_n:
            continue
        kind, _, name = node.partition(":")
        rows.append({"node": node, "kind": kind, "name": name, **c})
    rows.sort(key=lambda r: (r.get("ic") if r.get("ic") is not None else -9))
    return rows
