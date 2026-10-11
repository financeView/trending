"""Spec C own-history turnover → VOL_score (0..100 int or null); stock + basket."""
from __future__ import annotations

from typing import List, Mapping, MutableMapping, Optional, Sequence

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


def _bar_trade_date_str(raw_td) -> Optional[str]:
    if raw_td is None:
        return None
    if hasattr(raw_td, "isoformat"):
        return raw_td.isoformat()[:10]
    return str(raw_td)[:10]


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


def assign_vol_scores(
    rows: Sequence[MutableMapping],
    series_by_code: Mapping[str, Sequence[Mapping]],
    *,
    trade_date: str,
    vol_hist: int,
    min_samples: int,
    code_key: str = "ts_code",
) -> None:
    """Set each row's VOL_score from own-history turnovers on series_by_code[code].

    Does not mutate RS or other peer fields. Missing/empty series → VOL_score null.
    """
    td = str(trade_date)[:10]
    for r in rows:
        code = r.get(code_key)
        records = list(series_by_code.get(code) or []) if code else []
        turnovers = [
            turnover_from_bar(b.get("amount"), b.get("float_mv")) for b in records
        ]
        scores = compute_vol_scores(
            turnovers, vol_hist=vol_hist, min_samples=min_samples
        )
        vol = None
        for i, b in enumerate(records):
            if _bar_trade_date_str(b.get("trade_date")) == td:
                vol = scores[i] if i < len(scores) else None
        r["VOL_score"] = vol
