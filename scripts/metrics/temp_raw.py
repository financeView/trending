"""§5.1 predicates + §5.2 T_raw decision tree (P0.5 Task 2).

No hysteresis / FSM.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from scripts.metrics.params import MetricsParams

RANK: dict[str, int] = {
    "沸": 3,
    "热": 2,
    "温": 1,
    "平": 0,
    "凉": -1,
    "寒": -2,
    "冻": -3,
}

PRED_KEYS = (
    "stack_bull",
    "stack_bear",
    "slope_up",
    "slope_down",
    "slope_flat",
    "di_bull",
    "di_bear",
    "hot_body",
    "warm_body",
    "cold_body",
    "cool_body",
    "boil_boost",
    "freeze_boost",
    "flat_body",
)


def rank(t: str) -> int:
    """Signed rank(T): 沸=3 … 平=0 … 冻=-3."""
    try:
        return RANK[t]
    except KeyError as e:
        raise ValueError(f"unknown T={t!r}") from e


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return bool(int(v))
    if v is None:
        return False
    s = str(v).strip().lower()
    if s in {"1", "true", "yes"}:
        return True
    if s in {"0", "false", "no", ""}:
        return False
    return bool(int(s))


def _finite(v: Any) -> bool:
    if v is None:
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return x == x and x not in (float("inf"), float("-inf"))


def _get(feats: Mapping[str, Any], *names: str) -> Any:
    for n in names:
        if n in feats and feats[n] is not None and str(feats[n]).strip() != "":
            return feats[n]
    return None


def _truthy_computable(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v != v:  # NaN
            return False
        return bool(int(v))
    s = str(v).strip().lower()
    if s in {"1", "true", "yes"}:
        return True
    if s in {"0", "false", "no", ""}:
        return False
    return bool(v)


def compute_predicates(feats: Mapping[str, Any], params: MetricsParams) -> dict[str, bool]:
    """Boolean predicates exactly as metrics §5.1."""
    p = float(_get(feats, "P", "close_qfq", "close"))
    ma_f = float(_get(feats, "MA_f"))
    ma_s = float(_get(feats, "MA_s"))
    slope_f = float(_get(feats, "slope_f"))
    adx = float(_get(feats, "ADX"))
    sign = float(_get(feats, "sign"))
    sigma_pctile = float(_get(feats, "sigma_pctile"))
    ret_pctile = float(_get(feats, "ret_pctile"))

    stack_bull = p > ma_f and ma_f > ma_s
    stack_bear = p < ma_f and ma_f < ma_s
    slope_up = slope_f > params.slope_eps
    slope_down = slope_f < -params.slope_eps
    slope_flat = abs(slope_f) <= params.slope_eps
    di_bull = sign >= 0
    di_bear = sign <= 0

    hot_body = stack_bull and slope_up and adx >= params.adx_hot and di_bull
    warm_body = (not hot_body) and di_bull and (
        slope_up or (p > ma_f and adx >= params.adx_warm)
    )
    cold_body = stack_bear and slope_down and adx >= params.adx_hot and di_bear
    cool_body = (not cold_body) and di_bear and (
        slope_down or (p < ma_f and adx >= params.adx_warm)
    )

    boil_boost = (sigma_pctile >= params.vol_boil) or (ret_pctile >= params.ret_boil_pctile)
    freeze_boost = (sigma_pctile >= params.vol_freeze) or (
        ret_pctile <= params.ret_freeze_pctile
    )
    flat_body = (adx < params.adx_flat) or slope_flat

    return {
        "stack_bull": stack_bull,
        "stack_bear": stack_bear,
        "slope_up": slope_up,
        "slope_down": slope_down,
        "slope_flat": slope_flat,
        "di_bull": di_bull,
        "di_bear": di_bear,
        "hot_body": hot_body,
        "warm_body": warm_body,
        "cold_body": cold_body,
        "cool_body": cool_body,
        "boil_boost": boil_boost,
        "freeze_boost": freeze_boost,
        "flat_body": flat_body,
    }


def decide_t_raw(preds: Mapping[str, Any]) -> str:
    """§5.2 first-hit tree. ``preds`` uses §5.1 names (bool / 0/1)."""

    def b(k: str) -> bool:
        return _as_bool(preds.get(k, 0))

    if b("hot_body") and b("boil_boost"):
        return "沸"
    if b("hot_body"):
        return "热"
    if b("warm_body"):
        return "温"
    if b("cold_body") and b("freeze_boost"):
        return "冻"
    if b("cold_body"):
        return "寒"
    if b("cool_body"):
        return "凉"
    if b("flat_body"):
        return "平"
    return "平"


def features_computable(feats: Mapping[str, Any]) -> bool:
    flag = _truthy_computable(_get(feats, "computable"))
    if flag is False:
        return False
    needed = (
        _get(feats, "P", "close_qfq", "close"),
        _get(feats, "MA_f"),
        _get(feats, "MA_s"),
        _get(feats, "slope_f"),
        _get(feats, "ADX"),
        _get(feats, "sign"),
        _get(feats, "sigma_pctile"),
        _get(feats, "ret_pctile"),
    )
    return all(_finite(v) for v in needed)


def decide_t_raw_from_features(
    feats: Mapping[str, Any],
    params: MetricsParams,
) -> Optional[str]:
    """§5.1 from feature snapshot then §5.2. Not computable → None."""
    if not features_computable(feats):
        return None
    return decide_t_raw(compute_predicates(feats, params))
