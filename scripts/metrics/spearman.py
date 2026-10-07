"""Pure-Python / numpy Spearman correlation (no scipy)."""
from __future__ import annotations

from math import isfinite, sqrt
from typing import Optional, Sequence


def _avg_ranks(values: Sequence[float]) -> list[float]:
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i + 1
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        # 1-based average rank for tie group [i, j)
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[order[k]] = avg
        i = j
    return ranks


def spearman_corr(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Pearson correlation of average ranks. None if n<2 or zero variance."""
    if len(xs) != len(ys):
        raise ValueError("xs and ys length mismatch")
    pairs = [
        (float(x), float(y))
        for x, y in zip(xs, ys)
        if isfinite(float(x)) and isfinite(float(y))
    ]
    n = len(pairs)
    if n < 2:
        return None
    rx = _avg_ranks([p[0] for p in pairs])
    ry = _avg_ranks([p[1] for p in pairs])
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = 0.0
    den_x = 0.0
    den_y = 0.0
    for a, b in zip(rx, ry):
        dx = a - mean_x
        dy = b - mean_y
        num += dx * dy
        den_x += dx * dx
        den_y += dy * dy
    if den_x <= 0.0 or den_y <= 0.0:
        return None
    return num / sqrt(den_x * den_y)
