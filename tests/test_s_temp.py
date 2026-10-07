"""§5.4 S_temp unit cases (synthetic feature rows)."""
from pathlib import Path

from scripts.metrics.params import load_params
from scripts.metrics.s_temp import compute_s_temp

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_params(ROOT / "config" / "metrics" / "a_share_daily.yaml")


def _bullish_feats(**overrides):
    row = {
        "P": 110.0,
        "MA_s": 90.0,
        "slope_f": 0.02,
        "slope_s": 0.02,
        "ADX": 30.0,
        "sign": 1.0,
        "sigma_pctile": 0.5,
    }
    row.update(overrides)
    return row


def test_bullish_stack_s_temp_above_50():
    s = compute_s_temp(_bullish_feats(), "热", PARAMS)
    assert s is not None
    assert 50.0 < s <= 100.0


def test_null_t_raw_yields_null_s_temp():
    assert compute_s_temp(_bullish_feats(), None, PARAMS) is None


def test_missing_ma_yields_null_s_temp():
    feats = _bullish_feats()
    del feats["MA_s"]
    assert compute_s_temp(feats, "热", PARAMS) is None
