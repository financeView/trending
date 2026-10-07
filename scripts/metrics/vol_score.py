"""Spec C stock own-history turnover → VOL_score (0..100 int or null)."""
from __future__ import annotations

from typing import List, Optional, Sequence

from scripts.metrics.percentile import scores_0_100


def _finite(x) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or abs(v) == float("inf"):
        return None
    return v


def turnover_from_bar(amount, float_mv) -> Optional[float]:
    """amount/float_mv when both finite and float_mv > 0; else null."""
    a = _finite(amount)
    mv = _finite(float_mv)
    if a is None or mv is None or mv <= 0:
        return None
    return a / mv


def compute_vol_scores(
    turnovers: Sequence[Optional[float]],
    *,
    vol_hist: int,
    min_samples: int,
) -> List[Optional[int]]:
    """Own-history VOL_score on OHLC spine; today-null → null; min_samples gate."""
    n = len(turnovers)
    out: List[Optional[int]] = [None] * n
    for t in range(n):
        today = _finite(turnovers[t])
        if today is None:
            continue
        start = max(0, t + 1 - vol_hist)
        window = list(turnovers[start : t + 1])
        finite_n = sum(1 for v in window if _finite(v) is not None)
        if finite_n < min_samples:
            continue
        scores = scores_0_100(window)
        out[t] = scores[-1]
    return out
