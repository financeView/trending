"""§5.4 continuous S_temp from absolute features + T_raw (Spec C Task 2).

No cross-section / peer / RS inputs.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Optional

from scripts.metrics.params import MetricsParams
from scripts.metrics.temp_raw import rank


def clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _finite(v: Any) -> bool:
    if v is None:
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return isfinite(x)


def _get(feats: Mapping[str, Any], *names: str) -> Any:
    for n in names:
        if n in feats and feats[n] is not None and str(feats[n]).strip() != "":
            return feats[n]
    return None


def compute_s_temp(
    feats: Mapping[str, Any],
    t_raw: Optional[str],
    params: MetricsParams,
) -> Optional[float]:
    """metrics §5.4. Missing/non-finite required feats or null T_raw → None."""
    if t_raw is None:
        return None
    try:
        r = rank(str(t_raw))
    except ValueError:
        return None

    slope_f = _get(feats, "slope_f")
    slope_s = _get(feats, "slope_s")
    ma = _get(feats, "MA_s", "ma_s")
    adx = _get(feats, "ADX")
    sign = _get(feats, "sign")
    sigma = _get(feats, "sigma_pctile")
    p = _get(feats, "P", "close_qfq")
    needed = (slope_f, slope_s, ma, adx, sign, sigma, p)
    if not all(_finite(v) for v in needed):
        return None

    slope_f = float(slope_f)
    slope_s = float(slope_s)
    ma = float(ma)
    adx = float(adx)
    sign = float(sign)
    sigma = float(sigma)
    p = float(p)
    if ma == 0.0:
        return None

    dir = clip((slope_f + slope_s) / (2.0 * params.slope_scale), -1.0, 1.0)
    pos = clip((p / ma - 1.0) / params.band, -1.0, 1.0)
    str_ = clip((adx - params.adx_s_floor) / params.adx_s_span, 0.0, 1.0)

    bullish = max(0.0, dir) * str_ * max(0.0, pos) * (1.0 if sign >= 0 else 0.0)
    bearish = max(0.0, -dir) * str_ * max(0.0, -pos) * (1.0 if sign <= 0 else 0.0)
    S0 = 50.0 + 45.0 * (bullish - bearish)

    sign_trend = 1 if r > 0 else (-1 if r < 0 else 0)
    out = clip(S0 + params.s_vol_weight * (sigma - 0.5) * sign_trend, 0.0, 100.0)
    return float(out)
