"""
The attribution graph — how a realized outcome assigns credit backwards.

`pillar_correlation` in the ledger already answers "did this pillar's score
correlate with the return". This module exists because that is not the same
question as "did this pillar's contribution to THIS decision help", and only
the second one can justify changing a weight.

The difference is the weight itself. A pillar scoring 90 inside a composite
that weights it at 0.05 barely moved the decision; the same 90 at 0.40 moved
it a lot. A flat correlation treats both identically and therefore cannot
tell you what reweighting would have done — which is precisely the question
the loop needs answered.

So the graph is explicit:

    OUTCOME ──realized──> DECISION ──contributed──> NODE
       │                     │                        │
   excess return         action, regime           pillar / regime /
   direction             confidence, class        action / confidence

and every CONTRIBUTED edge carries both the node's TILT (how far it leaned,
normalised to -1..+1) and its WEIGHT (how much of the decision it was allowed
to move). Attribution multiplies them. That product, against the realized
excess return, is the quantity a reweighting proposal is actually about.

Three deliberate refusals, each a way this could quietly become dishonest:

  * A node with no tilt gets no credit and no blame. A pillar sitting at
    neutral 50 did not contribute to a decision that happened to work, and
    counting it as a winner is how a useless signal accumulates a reputation.

  * Excess return, never raw return. In a rising market every long call looks
    skilled; the ledger's `excess_return_pct` is already benchmark-relative
    and it is the only return this module reads.

  * Unmatured outcomes are skipped entirely, not treated as zero. A horizon
    that has not elapsed is unknown, and averaging unknowns as zeros drags
    every score toward neutral and makes the loop confident about nothing.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Node kinds.
PILLAR = "pillar"
REGIME = "regime"
ACTION = "action"
CONFIDENCE = "confidence"
SECTOR = "sector"
ASSET_CLASS = "asset_class"

NODE_KINDS = (PILLAR, REGIME, ACTION, CONFIDENCE, SECTOR, ASSET_CLASS)

# A pillar score is 0..100 with 50 as "no opinion".
PILLAR_NEUTRAL = 50.0

# Actions carry a direction of their own; a SELL that is followed by a fall is
# a correct call even though the excess return is negative. Attribution has to
# multiply the outcome by the intended direction or every bearish call in the
# book is scored as a loss — which is exactly how the existing by_action table
# reads REDUCE and SELL today.
ACTION_DIRECTION = {
    "BUY": 1.0, "ACCUMULATE": 1.0, "HOLD": 0.0, "REDUCE": -1.0, "SELL": -1.0,
}

CONFIDENCE_RANK = {"NONE": 0.0, "LOW": 0.33, "MEDIUM": 0.66, "HIGH": 1.0}


def node_id(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def _loads(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


def _tilt_from_score(score: float) -> float:
    """0..100 -> -1..+1, clipped. 50 is no opinion, not a weak buy."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, (s - PILLAR_NEUTRAL) / PILLAR_NEUTRAL))


def _decision_confidence(snap: Dict[str, Any]) -> str:
    """The ledger stores four separate confidence fields. The decision's
    confidence is the WEAKEST of the ones that were actually assessed: a call
    resting on high-conviction thesis but absent data is not a high-confidence
    call, and taking the max would let one strong leg mask a missing one."""
    levels = [snap.get(k) for k in
              ("conf_thesis", "conf_data", "conf_statistical_edge")]
    present = [str(x).upper() for x in levels
               if x and str(x).upper() in CONFIDENCE_RANK
               and str(x).upper() != "NONE"]
    if not present:
        return "NONE"
    return min(present, key=lambda L: CONFIDENCE_RANK[L])


def build(snapshot: Dict[str, Any], outcome: Dict[str, Any],
          weights: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    """One resolved prediction as a graph, or None if it cannot be attributed.

    `weights` defaults to the live pillar weights. Passing a candidate set is
    how a proposal is counterfactually evaluated: the same history, re-walked
    under different weights.
    """
    if not outcome or not outcome.get("matured"):
        return None
    excess = outcome.get("excess_return_pct")
    if excess is None:
        return None
    try:
        excess = float(excess)
    except (TypeError, ValueError):
        return None

    if weights is None:
        from backtest.pillars import CORE_WEIGHTS
        weights = dict(CORE_WEIGHTS)

    action = str(snapshot.get("action") or "").upper()
    direction = ACTION_DIRECTION.get(action)
    if direction is None:
        return None
    # A HOLD expresses no directional view, so nothing can be credited or
    # blamed for where the price went. Counting it would add noise with no
    # signal, at 70 of 304 rows.
    if direction == 0.0:
        return None

    # TWO FRAMES, and keeping them apart is the whole correctness of this
    # module. A pillar's tilt is a statement about the MARKET ("this looks
    # bearish"), so whether it was right is judged against the raw excess
    # return. A call's success is a statement about the DECISION ("selling was
    # correct"), so it is judged against the excess return signed by intent.
    #
    # Comparing a market-frame tilt to a call-frame outcome scores every
    # correct bearish pillar as a miss, which would drive the loop to
    # down-weight exactly the signals that worked on the short side.
    realized_market = excess                 # pillar frame
    realized_call = excess * direction       # decision frame

    pillars = _loads(snapshot.get("pillars_json"))
    edges: List[Dict[str, Any]] = []

    for name, score in pillars.items():
        tilt = _tilt_from_score(score)
        if tilt == 0.0:
            continue                      # neutral earns neither credit nor blame
        w = float(weights.get(name, 0.0))
        edges.append({
            "node": node_id(PILLAR, name), "kind": PILLAR, "name": name,
            "tilt": round(tilt, 6), "weight": round(w, 6),
            "contribution": round(tilt * w, 6),
            # Did this pillar lean the way the market actually went?
            "agreed": (tilt > 0) == (realized_market > 0),
            # The same lean expressed in the decision's frame, so a bearish
            # pillar inside a SELL that worked reads as the hit it was.
            "agreed_with_call": (tilt * direction > 0) == (realized_call > 0),
        })

    # Context nodes carry no tilt of their own — they are conditions the
    # decision was made under, not evidence that leaned. Their weight is 1.0
    # because the decision was wholly inside that condition.
    for kind, name in (
        (REGIME, snapshot.get("regime")),
        (ACTION, action),
        (CONFIDENCE, _decision_confidence(snapshot)),
        (SECTOR, snapshot.get("sector")),
        (ASSET_CLASS, snapshot.get("asset_class")),
    ):
        if not name or str(name).lower() in ("none", "unknown", ""):
            continue
        edges.append({
            "node": node_id(kind, str(name)), "kind": kind, "name": str(name),
            "tilt": None, "weight": 1.0, "contribution": None,
            # A context node is judged on whether the DECISION made under it
            # worked, which is the call frame.
            "agreed": realized_call > 0,
            "agreed_with_call": realized_call > 0,
        })

    return {
        "snapshot_id": snapshot.get("snapshot_id"),
        "ticker": snapshot.get("ticker"),
        "as_of": (snapshot.get("created_at") or "")[:10],
        "horizon_days": outcome.get("horizon_days"),
        "action": action,
        "direction": direction,
        "excess_return_pct": excess,
        # `realized` is the MARKET frame, because every consumer that
        # correlates it against a tilt (scorecard ic, verify's composite
        # metric) is asking a market question. Decision-frame scoring reads
        # `realized_call`.
        "realized": round(realized_market, 6),
        "realized_call": round(realized_call, 6),
        "edges": edges,
    }


def walk(graphs: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Invert the graphs: node id -> the observations attributable to it.

    This is the backward pass. Each observation keeps its date, because every
    downstream gate splits by TIME and a record without one cannot be purged
    or held out.
    """
    by_node: Dict[str, List[Dict[str, Any]]] = {}
    for g in graphs:
        if not g:
            continue
        for e in g.get("edges") or []:
            by_node.setdefault(e["node"], []).append({
                "snapshot_id": g.get("snapshot_id"),
                "ticker": g.get("ticker"),
                "as_of": g.get("as_of"),
                "horizon_days": g.get("horizon_days"),
                "kind": e["kind"], "name": e["name"],
                "tilt": e["tilt"], "weight": e["weight"],
                "contribution": e["contribution"],
                "agreed": e["agreed"],
                "agreed_with_call": e.get("agreed_with_call"),
                "realized": g.get("realized"),
                "realized_call": g.get("realized_call"),
            })
    return by_node


def load_resolved(horizon: int, limit: int = 5000,
                  source: str = "all") -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Matured (snapshot, outcome) pairs for one horizon, newest last.

    Reads through prediction_ledger's own quarantine filter rather than
    querying the tables directly — synthetic tickers and snapshots frozen by a
    non-canonical deployment are excluded there, and an attribution built on
    them would be learning from rows the ledger already knows are not evidence.
    """
    import sqlite3
    from data import prediction_ledger as PL

    conn = sqlite3.connect(PL._db())
    conn.row_factory = sqlite3.Row
    try:
        # _source_where already carries its own leading AND *and* folds in the
        # quarantine clause for every value of `source`, so it is spliced bare.
        # Adding either one again produces "AND AND" — a syntax error that an
        # over-broad except would turn into a silent empty attribution.
        rows = conn.execute(
            f"""SELECT s.*, o.horizon_days AS o_horizon, o.matured, o.excess_return_pct,
                       o.raw_return_pct, o.direction_correct, o.brier
                  FROM prediction_snapshots s
                  JOIN prediction_outcomes o ON o.snapshot_id = s.snapshot_id
                 WHERE o.horizon_days = ? AND o.matured = 1
                   {PL._source_where(source, 's')}
              ORDER BY s.created_at ASC
                 LIMIT ?""", (int(horizon), int(limit))).fetchall()
    except sqlite3.Error as e:
        # A malformed query here reads downstream as "no history to learn
        # from", which is indistinguishable from an honestly empty ledger and
        # would make the loop refuse every proposal for the wrong reason.
        raise RuntimeError(f"attribution query failed: {e}") from e
    finally:
        conn.close()

    out: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for r in rows:
        snap = dict(r)
        out.append((snap, {"horizon_days": snap.pop("o_horizon"),
                           "matured": snap.pop("matured"),
                           "excess_return_pct": snap.pop("excess_return_pct"),
                           "raw_return_pct": snap.pop("raw_return_pct"),
                           "direction_correct": snap.pop("direction_correct"),
                           "brier": snap.pop("brier")}))
    return out


def graphs_for(horizon: int, weights: Optional[Dict[str, float]] = None,
               limit: int = 5000) -> List[Dict[str, Any]]:
    """Every attributable resolved prediction at one horizon."""
    built = [build(s, o, weights) for s, o in load_resolved(horizon, limit)]
    return [g for g in built if g]
