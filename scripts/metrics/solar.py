"""§8.2 solar linear scorer: clamp, enter 谷雨 / exit 立秋, peak-only advance."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from scripts.metrics.params import Knot, MetricsParams

SOLAR_TERMS_ASC: Tuple[str, ...] = ("谷雨", "立夏", "夏至", "小暑", "大暑")
ENTER_TERM = "谷雨"
EXIT_TERM = "立秋"


def piecewise_linear_clamp(x: float, knots: Sequence[Knot]) -> float:
    """Interpolate between knots; clamp at endpoints with no extrapolation."""
    if len(knots) < 2:
        raise ValueError("knots need at least two points")
    xs = [k[0] for k in knots]
    ys = [k[1] for k in knots]
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for i in range(len(knots) - 1):
        x0, y0 = knots[i]
        x1, y1 = knots[i + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    raise RuntimeError("unreachable clamp")


def cut_stage(stage_score: float, cuts: Sequence[float]) -> str:
    """Map peak score to 谷雨…大暑. 立秋 is never produced here."""
    for i, c in enumerate(cuts):
        if stage_score < c:
            return SOLAR_TERMS_ASC[i]
    return SOLAR_TERMS_ASC[len(cuts)]


@dataclass
class SolarState:
    solar_term: Optional[str]
    stage_score: Optional[float]
    stage_score_raw: Optional[float]
    stage_score_peak: float
    P0: Optional[float] = None
    atr_pct_entry: Optional[float] = None
    g_raw: Optional[float] = None
    g_raw_eff: Optional[float] = None
    d_raw: Optional[float] = None
    v_raw: Optional[float] = None


def _idle() -> SolarState:
    return SolarState(
        solar_term=None,
        stage_score=None,
        stage_score_raw=None,
        stage_score_peak=0.0,
    )


def _keep_halted(prev: SolarState) -> SolarState:
    return SolarState(
        solar_term=prev.solar_term,
        stage_score=prev.stage_score,
        stage_score_raw=prev.stage_score_raw,
        stage_score_peak=prev.stage_score_peak,
        P0=prev.P0,
        atr_pct_entry=prev.atr_pct_entry,
        g_raw=prev.g_raw,
        g_raw_eff=prev.g_raw_eff,
        d_raw=prev.d_raw,
        v_raw=prev.v_raw,
    )


def step_solar(
    params: MetricsParams,
    prev: Optional[SolarState],
    *,
    entered_today: bool = False,
    exited_today: bool = False,
    right_side: bool = False,
    days_trading: int = 0,
    P_t: Optional[float] = None,
    sigma_pctile: Optional[float] = None,
    atr_pct: Optional[float] = None,
) -> SolarState:
    """Advance solar labels. Linear scorer runs only on persist days (FSM path)."""
    prior = prev if prev is not None else _idle()

    if entered_today:
        # Force 谷雨; scores 0; do not write v (or full scorer) into peak.
        return SolarState(
            solar_term=ENTER_TERM,
            stage_score=0.0,
            stage_score_raw=0.0,
            stage_score_peak=0.0,
            P0=P_t,
            atr_pct_entry=atr_pct,
        )

    if exited_today:
        # Force 立秋; public scores NULL (not 0). Internal peak reset for next entry.
        return SolarState(
            solar_term=EXIT_TERM,
            stage_score=None,
            stage_score_raw=None,
            stage_score_peak=0.0,
            P0=None,
            atr_pct_entry=None,
        )

    if not right_side:
        return _idle()

    # Persist: only advance when P and σ%ile are computable.
    if P_t is None or sigma_pctile is None or prior.P0 is None or prior.atr_pct_entry is None:
        return _keep_halted(prior)

    denom = max(prior.atr_pct_entry, params.atr_floor)
    g_raw = math.log(P_t / prior.P0) / denom
    g_raw_eff = max(g_raw, 0.0)
    d_raw = days_trading / params.stage_D0
    v_raw = float(sigma_pctile)

    g = piecewise_linear_clamp(g_raw_eff, params.knots_g)
    d = piecewise_linear_clamp(d_raw, params.knots_d)
    v = piecewise_linear_clamp(v_raw, params.knots_v)
    raw = params.w_g * g + params.w_d * d + params.w_v * v
    peak = max(prior.stage_score_peak, raw)
    term = cut_stage(peak, params.stage_cuts)
    return SolarState(
        solar_term=term,
        stage_score=peak,
        stage_score_raw=raw,
        stage_score_peak=peak,
        P0=prior.P0,
        atr_pct_entry=prior.atr_pct_entry,
        g_raw=g_raw,
        g_raw_eff=g_raw_eff,
        d_raw=d_raw,
        v_raw=v_raw,
    )
