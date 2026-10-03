"""Load metrics YAML → frozen MetricsParams (metrics §13 / P0.5 Task 1)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple, Union

import yaml

Knot = Tuple[float, float]
PathLike = Union[str, Path]


def _knots(raw: Sequence[Sequence[float]]) -> Tuple[Knot, ...]:
    out: list[Knot] = []
    for pair in raw:
        if len(pair) != 2:
            raise ValueError(f"knot must be [x, y], got {pair!r}")
        out.append((float(pair[0]), float(pair[1])))
    if len(out) < 2:
        raise ValueError("knots need at least two points")
    for a, b in zip(out, out[1:]):
        if b[0] <= a[0]:
            raise ValueError(f"knots x must be strictly increasing: {out}")
    return tuple(out)


@dataclass(frozen=True)
class MetricsParams:
    param_version: str
    price_adjust: str
    ma_fast: int
    ma_slow: int
    slope_n: int
    slope_eps: float
    slope_scale: float
    band: float
    adx_len: int
    adx_hot: float
    adx_warm: float
    adx_flat: float
    adx_s_floor: float
    adx_s_span: float
    vol_lookback: int
    vol_hist: int
    vol_boil: float
    vol_freeze: float
    ret_k: int
    ret_boil_pctile: float
    ret_freeze_pctile: float
    hysteresis_up: int
    hysteresis_down: int
    max_step: int
    s_vol_weight: float
    spearman_min: float
    atr_len: int
    atr_floor: float
    stage_D0: int
    w_g: float
    w_d: float
    w_v: float
    stage_cuts: Tuple[float, ...]
    knots_g: Tuple[Knot, ...]
    knots_d: Tuple[Knot, ...]
    knots_v: Tuple[Knot, ...]
    exit_tags_enabled: bool

    @property
    def min_history_temp(self) -> int:
        """metrics §3.3：温度最少交易日。"""
        return max(self.ma_slow + self.slope_n, self.adx_len * 2, self.vol_hist)


def load_params(path: PathLike) -> MetricsParams:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError("metrics yaml must be a mapping")
    if "require_solar_term_for_entry" in raw:
        raise ValueError(
            "require_solar_term_for_entry is forbidden (metrics C3 / §8.3); "
            "solar term must not gate right-side entry"
        )
    cuts = raw.get("stage_cuts") or []
    return MetricsParams(
        param_version=str(raw["param_version"]),
        price_adjust=str(raw.get("price_adjust", "qfq")),
        ma_fast=int(raw["ma_fast"]),
        ma_slow=int(raw["ma_slow"]),
        slope_n=int(raw["slope_n"]),
        slope_eps=float(raw["slope_eps"]),
        slope_scale=float(raw["slope_scale"]),
        band=float(raw["band"]),
        adx_len=int(raw["adx_len"]),
        adx_hot=float(raw["adx_hot"]),
        adx_warm=float(raw["adx_warm"]),
        adx_flat=float(raw["adx_flat"]),
        adx_s_floor=float(raw["adx_s_floor"]),
        adx_s_span=float(raw["adx_s_span"]),
        vol_lookback=int(raw["vol_lookback"]),
        vol_hist=int(raw["vol_hist"]),
        vol_boil=float(raw["vol_boil"]),
        vol_freeze=float(raw["vol_freeze"]),
        ret_k=int(raw["ret_k"]),
        ret_boil_pctile=float(raw["ret_boil_pctile"]),
        ret_freeze_pctile=float(raw["ret_freeze_pctile"]),
        hysteresis_up=int(raw["hysteresis_up"]),
        hysteresis_down=int(raw["hysteresis_down"]),
        max_step=int(raw["max_step"]),
        s_vol_weight=float(raw["s_vol_weight"]),
        spearman_min=float(raw["spearman_min"]),
        atr_len=int(raw["atr_len"]),
        atr_floor=float(raw["atr_floor"]),
        stage_D0=int(raw["stage_D0"]),
        w_g=float(raw["w_g"]),
        w_d=float(raw["w_d"]),
        w_v=float(raw["w_v"]),
        stage_cuts=tuple(float(x) for x in cuts),
        knots_g=_knots(raw["knots_g"]),
        knots_d=_knots(raw["knots_d"]),
        knots_v=_knots(raw["knots_v"]),
        exit_tags_enabled=bool(raw.get("exit_tags_enabled", False)),
    )
