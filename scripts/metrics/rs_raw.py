"""Spec C RS_raw: weighted multi-horizon ROC on close spine."""
from __future__ import annotations

from typing import List, Optional, Sequence

from scripts.metrics.params import MetricsParams


def _roc(closes: Sequence[Optional[float]], t: int, n: int) -> Optional[float]:
    if t - n < 0:
        return None
    pt, p0 = closes[t], closes[t - n]
    if pt is None or p0 is None or p0 == 0:
        return None
    return float(pt) / float(p0) - 1.0


def compute_rs_raw(
    closes: Sequence[Optional[float]], params: MetricsParams
) -> List[Optional[float]]:
    out: list[Optional[float]] = []
    for t in range(len(closes)):
        legs = [
            _roc(closes, t, 63),
            _roc(closes, t, 126),
            _roc(closes, t, 189),
            _roc(closes, t, 252),
        ]
        if any(x is None for x in legs):
            out.append(None)
        else:
            out.append(
                params.rs_w1 * legs[0]
                + params.rs_w2 * legs[1]
                + params.rs_w3 * legs[2]
                + params.rs_w4 * legs[3]
            )
    return out
