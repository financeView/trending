"""Asof peer RS assignment within one universe (stock / L2 / L1)."""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from scripts.metrics.percentile import scores_0_100


def stock_peer_eligible(row: Mapping, *, quarantine: set[str]) -> bool:
    ts = row.get("ts_code")
    if ts is None or ts in quarantine:
        return False
    if row.get("hard_frozen"):
        return False
    if row.get("_is_suspended"):
        return False
    if row.get("RS_raw") is None:
        return False
    return True


def basket_peer_eligible(row: Mapping) -> bool:
    return row.get("T") is not None and row.get("RS_raw") is not None


def assign_peer_rs(
    rows: list[dict],
    *,
    eligible: Callable[[dict], bool],
    raw_key: str = "RS_raw",
    out_key: str = "RS",
) -> None:
    """In-place: peer-percentile ``out_key`` among eligible ``raw_key`` values."""
    values: list[Optional[float]] = []
    for r in rows:
        if eligible(r):
            values.append(r.get(raw_key))  # type: ignore[arg-type]
        else:
            values.append(None)
    scores = scores_0_100(values)
    for r, s in zip(rows, scores):
        r[out_key] = s
