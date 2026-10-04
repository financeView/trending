"""§5.3 hysteresis: bootstrap, max_step, pending (P0.5 Task 3).

State is in-memory only (T_prev, pending_target, pending_count). No FSM.
"""
from __future__ import annotations

from typing import Optional

from scripts.metrics.params import MetricsParams
from scripts.metrics.temp_raw import RANK, rank

INV_RANK: dict[int, str] = {v: k for k, v in RANK.items()}


def inv_rank(r: int) -> str:
    try:
        return INV_RANK[r]
    except KeyError as e:
        raise ValueError(f"unknown rank={r!r}") from e


def same_side(a: str, b: str) -> bool:
    ra, rb = rank(a), rank(b)
    return (ra > 0 and rb > 0) or (ra < 0 and rb < 0)


def _clip(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


class Hysteresis:
    """Replay-only hysteresis. Caller must not persist this as engine_state."""

    def __init__(self, params: MetricsParams) -> None:
        self.params = params
        self.T_prev: Optional[str] = None
        self.pending_target: Optional[str] = None
        self.pending_count: int = 0

    def step(self, t_raw: Optional[str], *, R: bool = False) -> Optional[str]:
        """One trade-day close. ``t_raw=None`` does not advance state; returns None.

        §5.3.1: after a null stretch with ``R=false``, ``T_prev`` is unavailable so
        the next non-null day re-bootstraps from synthetic 平. While ``R=true``,
        null keeps ``T_prev`` (FSM soft-fill path).
        """
        if t_raw is None:
            if not R:
                self.T_prev = None
                self.pending_target = None
                self.pending_count = 0
            return None

        if self.T_prev is None:
            # §5.3.1 bootstrap: synthetic 平, then §5.3.2
            self.T_prev = "平"
            self.pending_target = None
            self.pending_count = 0

        t = self._step_daily(t_raw, R=R)
        self.T_prev = t
        return t

    def _step_daily(self, desired: str, *, R: bool) -> str:
        t_prev = self.T_prev
        assert t_prev is not None
        delta = rank(desired) - rank(t_prev)
        max_step = self.params.max_step

        # A. extreme adjacency: 热→沸 / 寒→冻
        if (
            desired in {"沸", "冻"}
            and t_prev in {"热", "寒"}
            and same_side(desired, t_prev)
        ):
            stepped = desired
        # B. right-side exit fast-path
        elif R and rank(desired) <= 0:
            stepped_rank = rank(t_prev) + _clip(delta, -max_step, max_step)
            if stepped_rank > 0:
                stepped_rank = 0
            stepped = inv_rank(stepped_rank)
        # C. regular max_step
        else:
            stepped = inv_rank(rank(t_prev) + _clip(delta, -max_step, max_step))

        if stepped == t_prev:
            self.pending_target = None
            self.pending_count = 0
            return t_prev

        need = (
            self.params.hysteresis_up
            if rank(stepped) > rank(t_prev)
            else self.params.hysteresis_down
        )
        if self.pending_target == stepped:
            self.pending_count += 1
        else:
            self.pending_target = stepped
            self.pending_count = 1
        if self.pending_count >= need:
            self.pending_target = None
            self.pending_count = 0
            return stepped
        return t_prev
