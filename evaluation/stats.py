"""
Small, dependency-free statistics for the scorecard.

Everything in evaluation/ aggregates PER CALL DATE first and then across dates,
because names called on the same day share the same market move: 70 calls on
one day are one observation of "how did the desk do that day", not 70. The
across-date standard error is Newey-West with lag h-1, because a 5-day outcome
called on Monday and one called on Tuesday share four of their five days.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence


def mean(xs: Sequence[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def ranks(xs: Sequence[float]) -> List[float]:
    """1-based ranks, ties averaged (what Spearman needs)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = r
        i = j + 1
    return out


def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    return pearson(ranks(xs), ranks(ys))


def newey_west_se(xs: Sequence[float], lag: int) -> Optional[float]:
    """HAC standard error of the mean, Bartlett weights."""
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    d = [x - m for x in xs]
    lag = max(0, min(int(lag), n - 2))
    s = sum(v * v for v in d) / n
    for k in range(1, lag + 1):
        g = sum(d[t] * d[t - k] for t in range(k, n)) / n
        s += 2.0 * (1.0 - k / (lag + 1.0)) * g
    if s <= 0:
        return None
    return math.sqrt(s / n)


def t_stat(xs: Sequence[float], lag: int) -> Optional[float]:
    se = newey_west_se(xs, lag)
    m = mean(xs)
    if se is None or m is None or se == 0:
        return None
    return m / se


def r(x: Optional[float], nd: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), nd)
