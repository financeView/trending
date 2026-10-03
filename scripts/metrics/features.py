"""OHLC → §4.1 temperature features (P0.5 Task 1).

No T_raw / FSM — pure feature layer only.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from scripts.metrics.params import MetricsParams

FEATURE_COLS = (
    "MA_f",
    "MA_s",
    "slope_f",
    "slope_s",
    "ADX",
    "plus_di",
    "minus_di",
    "sign",
    "sigma_n",
    "sigma_pctile",
    "ret_k",
    "ret_pctile",
    "atr_pct",
    "computable",
)


def _col(df: pd.DataFrame, *names: str) -> pd.Series:
    for n in names:
        if n in df.columns:
            return df[n].astype(float)
    raise KeyError(f"need one of {names}, got columns={list(df.columns)}")


def _wilder_smooth(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder RMA; first value at index n-1 is SMA of first n samples."""
    out = np.full(len(x), np.nan, dtype=float)
    if len(x) < n or n <= 0:
        return out
    seed = np.nanmean(x[:n])
    if not np.isfinite(seed):
        return out
    out[n - 1] = seed
    for i in range(n, len(x)):
        prev = out[i - 1]
        xi = x[i]
        if not np.isfinite(prev) or not np.isfinite(xi):
            out[i] = np.nan
        else:
            out[i] = (prev * (n - 1) + xi) / n
    return out


def _adx_di_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    n: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Wilder ADX / +DI / -DI / ATR. ADX first usable ~ 2*n-1."""
    m = len(close)
    tr = np.full(m, np.nan)
    plus_dm = np.full(m, np.nan)
    minus_dm = np.full(m, np.nan)
    for i in range(1, m):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0

    atr = _wilder_smooth(tr[1:], n)
    sm_plus = _wilder_smooth(plus_dm[1:], n)
    sm_minus = _wilder_smooth(minus_dm[1:], n)
    # align to original length (index 0 unused for TR)
    atr_full = np.full(m, np.nan)
    plus_full = np.full(m, np.nan)
    minus_full = np.full(m, np.nan)
    atr_full[1:] = atr
    plus_full[1:] = sm_plus
    minus_full[1:] = sm_minus

    plus_di = np.full(m, np.nan)
    minus_di = np.full(m, np.nan)
    dx = np.full(m, np.nan)
    for i in range(m):
        a = atr_full[i]
        if not np.isfinite(a) or a == 0:
            continue
        p = plus_full[i]
        mn = minus_full[i]
        if not np.isfinite(p) or not np.isfinite(mn):
            continue
        plus_di[i] = 100.0 * p / a
        minus_di[i] = 100.0 * mn / a
        s = plus_di[i] + minus_di[i]
        if s > 0:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / s
        else:
            dx[i] = 0.0

    # ADX = Wilder smooth of DX; seed at first finite window of n DX values
    adx = np.full(m, np.nan)
    # first DX typically at index n (after n TR smooth starts at n)
    finite_idx = [i for i in range(m) if np.isfinite(dx[i])]
    if len(finite_idx) >= n:
        start = finite_idx[n - 1]
        # SMA of first n finite DX ending at start
        window = [dx[i] for i in finite_idx[:n]]
        adx[start] = float(np.mean(window))
        prev = adx[start]
        for i in range(start + 1, m):
            if not np.isfinite(dx[i]) or not np.isfinite(prev):
                adx[i] = np.nan
                prev = np.nan
            else:
                prev = (prev * (n - 1) + dx[i]) / n
                adx[i] = prev

    return adx, plus_di, minus_di, atr_full


def _empirical_pctile(series: pd.Series, hist: int) -> pd.Series:
    """Current value's empirical percentile over the past `hist` bars ∈[0,1].

    Uses finite samples in ``[i-hist+1, i]``. Requires ``i >= hist-1`` so the
    window spans ``hist`` trading days (§3.3 / §4.1); early NaNs inside the
    window (e.g. before σ_n warms up) are skipped.
    """
    vals = series.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if i < hist - 1:
            continue
        v = vals[i]
        if not np.isfinite(v):
            continue
        lo = i - hist + 1
        window = vals[lo : i + 1]
        finite = window[np.isfinite(window)]
        if len(finite) == 0:
            continue
        out[i] = float(np.sum(finite <= v) / len(finite))
    return pd.Series(out, index=series.index)


def compute_features(
    ohlc: pd.DataFrame,
    params: MetricsParams,
    *,
    min_history: Optional[int] = None,
) -> pd.DataFrame:
    """Compute §4.1 features from sorted OHLC.

    Requires ``close_qfq``. High/low: ``high_qfq``/``low_qfq`` or ``high``/``low``.
    Short history → feature nulls and ``computable=False`` (§3.3).
    """
    if ohlc.empty:
        return pd.DataFrame(columns=list(FEATURE_COLS))

    close = _col(ohlc, "close_qfq", "close")
    high = _col(ohlc, "high_qfq", "high")
    low = _col(ohlc, "low_qfq", "low")

    need = min_history if min_history is not None else params.min_history_temp
    n = len(close)

    ma_f = close.rolling(params.ma_fast, min_periods=params.ma_fast).mean()
    ma_s = close.rolling(params.ma_slow, min_periods=params.ma_slow).mean()

    def _ln_slope(ma: pd.Series) -> pd.Series:
        prev = ma.shift(params.slope_n)
        ok = (ma > 0) & (prev > 0)
        out = pd.Series(np.nan, index=ma.index, dtype=float)
        out.loc[ok] = np.log(ma.loc[ok]) - np.log(prev.loc[ok])
        return out

    slope_f = _ln_slope(ma_f)
    slope_s = _ln_slope(ma_s)

    h = high.to_numpy(dtype=float)
    lo = low.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    adx, plus_di, minus_di, atr_adx = _adx_di_atr(h, lo, c, params.adx_len)
    if params.atr_len == params.adx_len:
        atr = atr_adx
    else:
        _, _, _, atr = _adx_di_atr(h, lo, c, params.atr_len)
    sign = np.sign(plus_di - minus_di)
    sign[~np.isfinite(plus_di) | ~np.isfinite(minus_di)] = np.nan

    log_ret = np.log(close / close.shift(1))
    sigma_n = log_ret.rolling(params.vol_lookback, min_periods=params.vol_lookback).std(ddof=0)
    sigma_pctile = _empirical_pctile(sigma_n, params.vol_hist)

    ret_k = close / close.shift(params.ret_k) - 1.0
    ret_pctile = _empirical_pctile(ret_k, params.vol_hist)

    atr_pct = pd.Series(atr, index=close.index) / close
    atr_pct = atr_pct.where(close > 0)

    # §3.3 gate: enough bars AND core temp features present
    computable = np.zeros(n, dtype=bool)
    if n >= need:
        for i in range(need - 1, n):
            ok = (
                np.isfinite(ma_f.iloc[i])
                and np.isfinite(ma_s.iloc[i])
                and np.isfinite(slope_f.iloc[i])
                and np.isfinite(slope_s.iloc[i])
                and np.isfinite(adx[i])
                and np.isfinite(sign[i])
                and np.isfinite(sigma_n.iloc[i])
                and np.isfinite(sigma_pctile.iloc[i])
                and np.isfinite(ret_k.iloc[i])
                and np.isfinite(ret_pctile.iloc[i])
            )
            computable[i] = bool(ok)

    def _mask(s: pd.Series | np.ndarray) -> pd.Series:
        ser = pd.Series(s, index=close.index, dtype=float)
        return ser.where(computable)

    out = pd.DataFrame(
        {
            "MA_f": _mask(ma_f),
            "MA_s": _mask(ma_s),
            "slope_f": _mask(slope_f),
            "slope_s": _mask(slope_s),
            "ADX": _mask(adx),
            "plus_di": _mask(plus_di),
            "minus_di": _mask(minus_di),
            "sign": _mask(sign),
            "sigma_n": _mask(sigma_n),
            "sigma_pctile": _mask(sigma_pctile),
            "ret_k": _mask(ret_k),
            "ret_pctile": _mask(ret_pctile),
            "atr_pct": _mask(atr_pct),
            "computable": computable,
        },
        index=close.index,
    )
    # when not computable, keep atr_pct raw if available? Plan: nulls when short.
    # Already masked. For rows before need, all NaN + computable False — good.
    return out
