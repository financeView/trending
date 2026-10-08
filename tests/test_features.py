"""Offline §4.1 feature-layer tests (synthetic OHLC, no network)."""
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.metrics.features import compute_features
from scripts.metrics.params import load_params

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_params(ROOT / "config" / "metrics" / "a_share_daily.yaml")


def _ohlc(close: np.ndarray) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "close_qfq": close,
            "high": close * 1.01,
            "low": close * 0.99,
        }
    )


def test_load_params_p05_yaml():
    assert PARAMS.param_version == "p05-v3"
    assert PARAMS.slope_scale == 0.02
    assert PARAMS.band == 0.15
    assert PARAMS.adx_s_floor == 15
    assert PARAMS.adx_s_span == 25
    assert PARAMS.s_vol_weight == 5
    assert PARAMS.spearman_min == 0.55
    assert PARAMS.rs_w1 == 0.4
    assert PARAMS.vol_score_min_samples == 60
    assert PARAMS.knots_g[0] == (0.0, 0.0)
    assert PARAMS.knots_g[-1] == (5.0, 1.0)
    assert PARAMS.knots_d[1] == (0.25, 0.3)
    assert PARAMS.knots_v[-2] == (0.9, 0.8)
    assert PARAMS.min_history_temp == 252


def test_known_sma():
    close = np.arange(1.0, 301.0)
    feat = compute_features(_ohlc(close), PARAMS)
    assert bool(feat["computable"].iloc[-1])
    assert feat["MA_f"].iloc[-1] == np.mean(close[-PARAMS.ma_fast :])
    assert feat["MA_s"].iloc[-1] == np.mean(close[-PARAMS.ma_slow :])
    flat = np.full(300, 10.0)
    feat_flat = compute_features(_ohlc(flat), PARAMS)
    assert feat_flat["MA_f"].iloc[-1] == 10.0
    assert feat_flat["MA_s"].iloc[-1] == 10.0


def test_adx_smoke_uptrend():
    close = np.linspace(10.0, 40.0, 300)
    feat = compute_features(_ohlc(close), PARAMS)
    last = feat.iloc[-1]
    assert bool(last["computable"])
    assert np.isfinite(last["ADX"])
    assert last["ADX"] > 0
    assert last["sign"] == 1.0


def test_sigma_pctile_in_unit_interval():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.012, 400)
    close = 10.0 * np.cumprod(1.0 + rets)
    feat = compute_features(_ohlc(close), PARAMS)
    ok = feat.loc[feat["computable"], "sigma_pctile"]
    assert len(ok) > 0
    assert float(ok.min()) >= 0.0
    assert float(ok.max()) <= 1.0
    ret_ok = feat.loc[feat["computable"], "ret_pctile"]
    assert float(ret_ok.min()) >= 0.0
    assert float(ret_ok.max()) <= 1.0


def test_short_series_not_computable():
    close = np.linspace(10.0, 12.0, 80)
    feat = compute_features(_ohlc(close), PARAMS)
    assert not bool(feat["computable"].any())
    for col in ("MA_f", "MA_s", "ADX", "sigma_pctile", "ret_pctile", "atr_pct"):
        assert feat[col].isna().all()
