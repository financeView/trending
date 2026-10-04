"""§6 right-side FSM + §6.0 events (P0.5 Task 4).

In-memory replay only. Solar scorer is stubbed: enter → 谷雨 / scores 0;
exit → 立秋 / scores null. Persist days keep the prior term (no §8.2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

ENTER_T = frozenset({"热", "沸"})
EXIT_T = frozenset({"平", "凉", "寒", "冻"})
RECONFIRM_T = frozenset({"热", "沸"})

EVENT_ENTER = "ENTER_RIGHT"
EVENT_EXIT = "EXIT_RIGHT"
EVENT_WARM_TO_HOT = "WARM_TO_HOT"

EXIT_KIND_TEMPERATURE = "temperature"
EXIT_KIND_UNTRADABLE = "forced_exit_untradable"

SOLAR_GRAIN_RAIN = "谷雨"
SOLAR_LIQIU = "立秋"


def _event(name: str, t: Optional[str], detail: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {"event": name, "T": t, "detail": dict(detail or {})}


@dataclass
class RightSideFsm:
    """Replay-only right-side state. Caller must not persist this as engine_state."""

    R: bool = False
    right_side_days_natural: int = 0
    right_side_days_trading: int = 0
    T_last_valid: Optional[str] = None
    T_prev_valid: Optional[str] = None
    P0: Optional[float] = None
    atr_pct_entry: Optional[float] = None
    stage_score_peak: float = 0.0
    solar_term: Optional[str] = None
    stage_score: Optional[float] = None
    stage_score_raw: Optional[float] = None
    just_exited_today: bool = False
    tag_warm_to_hot: bool = False
    tag_warm_to_flat: bool = False
    T_fsm: Optional[str] = None
    T_filled: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)

    def step_trade_day(
        self,
        T: Optional[str],
        *,
        hard_frozen: bool = False,
        P_t: Optional[float] = None,
        atr_pct: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """One trade-day close after §5. Returns structured events for this day."""
        self.tag_warm_to_hot = False
        self.tag_warm_to_flat = False
        self.just_exited_today = False
        self.T_filled = False
        self.events = []
        if not self.R:
            self.solar_term = None
            self.stage_score = None
            self.stage_score_raw = None

        # 1) hard_frozen first: end R; no same-day temperature enter
        if self.R and hard_frozen:
            t_event = T if T is not None else self.T_last_valid
            self._force_exit(t_event, exit_kind=EXIT_KIND_UNTRADABLE)
            return list(self.events)

        if T is None and not self.R:
            self.T_fsm = None
            return []

        if T is None and self.R:
            self.T_fsm = self.T_last_valid
            self.T_filled = True
        else:
            self.T_fsm = T

        t_fsm = self.T_fsm

        if not self.R:
            if t_fsm in ENTER_T and not hard_frozen:
                self.R = True
                self.right_side_days_natural = 0
                self.right_side_days_trading = 0
                self.P0 = P_t
                self.atr_pct_entry = atr_pct
                self.stage_score_peak = 0.0
                self.tag_warm_to_hot = True
                self.solar_term = SOLAR_GRAIN_RAIN
                self.stage_score = 0.0
                self.stage_score_raw = 0.0
                self.events.append(_event(EVENT_ENTER, t_fsm))
        else:
            if t_fsm in EXIT_T:
                self._force_exit(t_fsm, exit_kind=EXIT_KIND_TEMPERATURE)
            else:
                self.right_side_days_trading += 1
                if self.T_prev_valid == "温" and t_fsm in RECONFIRM_T:
                    self.tag_warm_to_hot = True
                    self.events.append(_event(EVENT_WARM_TO_HOT, t_fsm))
                # §8 stub: keep yesterday solar (enter already forced 谷雨)

        self.T_prev_valid = t_fsm
        if T is not None:
            self.T_last_valid = T
        return list(self.events)

    def bump_natural_days(self, n: int = 1) -> None:
        """§6.3: add natural days while R (trade-day EOD and/or calendar gaps)."""
        if n < 0:
            raise ValueError(f"n must be >= 0, got {n}")
        if self.R and not self.just_exited_today:
            self.right_side_days_natural += n

    def _force_exit(self, t_for_event: Optional[str], *, exit_kind: str) -> None:
        self.R = False
        self.tag_warm_to_flat = True
        self.solar_term = SOLAR_LIQIU
        self.stage_score = None
        self.stage_score_raw = None
        self.stage_score_peak = 0.0
        self.right_side_days_natural = 0
        self.right_side_days_trading = 0
        self.just_exited_today = True
        self.events.append(
            _event(EVENT_EXIT, t_for_event, {"exit_kind": exit_kind})
        )
