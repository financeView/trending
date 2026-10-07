"""Single-symbol replay: hysteresis + FSM + solar (Strategy A, in-memory only)."""
from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from scripts.metrics.features import compute_features
from scripts.metrics.fsm import EVENT_ENTER, EVENT_EXIT, RightSideFsm
from scripts.metrics.hysteresis import Hysteresis
from scripts.metrics.params import MetricsParams
from scripts.metrics.rs_raw import compute_rs_raw
from scripts.metrics.solar import piecewise_linear_clamp, step_solar, SOLAR_TERMS_ASC, SolarState
from scripts.metrics.temp_raw import decide_t_raw_from_features

_TERM_ORD = {t: i for i, t in enumerate(SOLAR_TERMS_ASC)}


def _opt_float(day: Mapping[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        if k in day and day[k] is not None:
            return float(day[k])
    return None


def replay_days(
    params: MetricsParams,
    days: Sequence[Mapping[str, Any]],
    *,
    init: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Replay a fixture day list. Each day may supply ``T`` (post-hyst) and/or ``T_raw``."""
    hyst = Hysteresis(params)
    fsm = RightSideFsm()
    if init:
        for key, val in init.items():
            if not hasattr(fsm, key):
                raise AttributeError(f"unknown FSM init field {key!r}")
            setattr(fsm, key, val)
    solar: Optional[SolarState] = None
    prev_term: Optional[str] = None
    out: list[dict[str, Any]] = []

    for day in days:
        t_raw = day["T_raw"] if "T_raw" in day else None
        if "T" in day:
            t = day["T"]
            if t is not None:
                hyst.T_prev = t
                hyst.pending_target = None
                hyst.pending_count = 0
        elif "T_raw" in day:
            t = hyst.step(t_raw, R=fsm.R)
        else:
            t = None

        p_t = _opt_float(day, "P", "P_t")
        sigma = _opt_float(day, "sigma_pctile")
        atr = _opt_float(day, "atr_pct")
        hard = bool(day.get("hard_frozen", False))
        events = fsm.step_trade_day(t, hard_frozen=hard, P_t=p_t, atr_pct=atr)
        names = [e["event"] for e in events]
        entered = EVENT_ENTER in names
        exited = EVENT_EXIT in names
        solar = step_solar(
            params,
            solar,
            entered_today=entered,
            exited_today=exited,
            right_side=fsm.R,
            days_trading=fsm.right_side_days_trading,
            P_t=p_t,
            sigma_pctile=sigma,
            atr_pct=atr,
        )
        fsm.solar_term = solar.solar_term
        fsm.stage_score = solar.stage_score
        fsm.stage_score_raw = solar.stage_score_raw
        fsm.stage_score_peak = solar.stage_score_peak

        g_clamped: Optional[float] = None
        if solar.g_raw_eff is not None:
            g_clamped = piecewise_linear_clamp(solar.g_raw_eff, params.knots_g)

        term_jump: Optional[int] = None
        if prev_term in _TERM_ORD and solar.solar_term in _TERM_ORD:
            term_jump = int(_TERM_ORD[solar.solar_term] - _TERM_ORD[prev_term])

        exit_kind = None
        for e in events:
            if e["event"] == EVENT_EXIT:
                exit_kind = (e.get("detail") or {}).get("exit_kind")

        snap: dict[str, Any] = {
            "trade_date": day.get("trade_date"),
            "T": fsm.T_fsm,
            "T_raw": t_raw,
            "R": fsm.R,
            "events": names,
            "event_records": list(events),
            "exit_kind": exit_kind,
            "tag_warm_to_hot": fsm.tag_warm_to_hot,
            "tag_warm_to_flat": fsm.tag_warm_to_flat,
            "solar_term": fsm.solar_term,
            "stage_score": fsm.stage_score,
            "stage_score_raw": fsm.stage_score_raw,
            "stage_score_peak": fsm.stage_score_peak,
            "days_trading": fsm.right_side_days_trading,
            # Pre-EOD value (enter day still 0); persist uses days_natural_after_bump.
            "days_natural": fsm.right_side_days_natural,
            "T_filled": fsm.T_filled,
            "g_raw": solar.g_raw,
            "g_raw_eff": solar.g_raw_eff,
            "g_clamped": g_clamped,
            "v_raw": solar.v_raw,
            "term_jump": term_jump,
            "hard_frozen": hard,
        }
        # §6.3: every natural day EOD while R (incl. this trade day), then calendar gaps.
        fsm.bump_natural_days(1)
        gap = int(day.get("natural_bump_after", 0) or 0)
        if gap:
            fsm.bump_natural_days(gap)
        snap["days_natural_after_bump"] = fsm.right_side_days_natural
        out.append(snap)
        prev_term = fsm.solar_term
    return out


def _as_trade_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _opt_finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(x):
        return None
    return x


def _feat_map(row: Mapping[str, Any], close: Optional[float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if k == "computable":
            try:
                out[k] = bool(v) and not (isinstance(v, float) and not isfinite(v))
            except (TypeError, ValueError):
                out[k] = False
        else:
            out[k] = _opt_finite(v)
    if close is not None:
        out["P"] = close
        out["close_qfq"] = close
    return out


def replay_from_ohlc(
    params: MetricsParams,
    records: Sequence[Mapping[str, Any]],
    *,
    min_history: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Full-day replay from ≤D bars (in-memory). No engine_state.

    ``records`` must be sorted by ``trade_date`` and include ``close_qfq`` plus
    high/low (``high_qfq``/``low_qfq`` or ``high``/``low``). ``hard_frozen`` for
    each day is ``bool(is_st)`` on that bar.
    """
    if not records:
        return []
    df = pd.DataFrame(list(records))
    df = df.sort_values("trade_date").reset_index(drop=True)
    feat = compute_features(df, params, min_history=min_history)
    days: list[dict[str, Any]] = []
    for i in range(len(df)):
        bar = df.iloc[i]
        close = _opt_finite(bar.get("close_qfq", bar.get("close")))
        feat_row = feat.iloc[i] if i < len(feat) else {}
        feats = _feat_map(feat_row, close)
        t_raw = decide_t_raw_from_features(feats, params)
        hard = bool(int(bar.get("is_st") or 0))
        days.append(
            {
                "trade_date": _as_trade_date(bar["trade_date"]),
                "T_raw": t_raw,
                "hard_frozen": hard,
                "P": close,
                "sigma_pctile": feats.get("sigma_pctile"),
                "atr_pct": feats.get("atr_pct"),
                "close_qfq": close,
                "float_mv": _opt_finite(bar.get("float_mv")),
                "amount": _opt_finite(bar.get("amount")),
                "is_suspended": bool(int(bar.get("is_suspended") or 0)),
            }
        )
    for i, day in enumerate(days[:-1]):
        d0 = date.fromisoformat(str(day["trade_date"]))
        d1 = date.fromisoformat(str(days[i + 1]["trade_date"]))
        bump = (d1 - d0).days - 1
        if bump > 0:
            day["natural_bump_after"] = bump
    snaps = replay_days(params, days)
    closes = [day.get("close_qfq") for day in days]
    rs_series = compute_rs_raw(closes, params)
    for i, (snap, day) in enumerate(zip(snaps, days)):
        snap["close_qfq"] = day.get("close_qfq")
        snap["float_mv"] = day.get("float_mv")
        snap["amount"] = day.get("amount")
        snap["hard_frozen"] = bool(day.get("hard_frozen"))
        snap["is_suspended"] = bool(day.get("is_suspended"))
        snap["RS_raw"] = rs_series[i] if i < len(rs_series) else None
    return snaps
