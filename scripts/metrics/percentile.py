"""Spec C closed percentile_rank → 0..100 int scores."""
from __future__ import annotations

from typing import List, Optional, Sequence


def _finite_pairs(values: Sequence[Optional[float]]) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for i, v in enumerate(values):
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x == x and abs(x) != float("inf"):  # finite
            out.append((i, x))
    return out


def scores_0_100(values: Sequence[Optional[float]]) -> List[Optional[int]]:
    n = len(values)
    result: List[Optional[int]] = [None] * n
    pairs = _finite_pairs(values)
    if len(pairs) <= 1:
        return result
    # sort by value
    ordered = sorted(pairs, key=lambda t: t[1])
    # average ranks (1-based)
    ranks = [0.0] * len(ordered)
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        # ranks i..j inclusive → average of (i+1)..(j+1)
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    m = len(ordered)
    for (idx, _val), r in zip(ordered, ranks):
        p = (r - 1.0) / (m - 1.0)
        result[idx] = int(round(100.0 * p))
    return result
