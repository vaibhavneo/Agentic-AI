"""
The self-improvement loop: attribute outcomes, propose a change, prove it out
of sample, apply it, and roll it back when it stops holding.

Read `surface.py` first — it is the safety boundary, and it declares both what
the loop may touch and what it deliberately may not.
"""
from __future__ import annotations

__all__ = ["surface", "graph", "scorecard", "propose", "verify", "config",
           "ledger", "loop"]
