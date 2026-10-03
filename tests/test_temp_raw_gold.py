"""Gold + API tests for §5.1 predicates and §5.2 T_raw (no hysteresis)."""
import csv
from pathlib import Path

from scripts.metrics.params import load_params
from scripts.metrics.temp_raw import (
    PRED_KEYS,
    RANK,
    compute_predicates,
    decide_t_raw,
    decide_t_raw_from_features,
    rank,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "fixtures" / "temp_raw_gold.csv"
PARAMS = load_params(ROOT / "config" / "metrics" / "a_share_daily.yaml")
STUB_COLS = (
    "above_ma20",
    "above_ma60",
    "ma20_slope_up",
    "ma60_slope_up",
    "adx_ge_hot",
    "adx_ge_warm",
    "adx_lt_flat",
    "vol_high",
    "ret_extreme_up",
    "ret_extreme_down",
)


def _load_gold():
    with GOLD.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_temp_raw_gold():
    rows = _load_gold()
    assert len(rows) >= 20
    header = set(rows[0].keys())
    for col in STUB_COLS:
        assert col not in header, col
    for k in PRED_KEYS:
        assert k in header, k
    seen = set()
    for row in rows:
        got_preds = decide_t_raw(row)
        assert got_preds == row["expect_T_raw"], (row["id"], got_preds, row["expect_T_raw"])
        computed = compute_predicates(row, PARAMS)
        for k in PRED_KEYS:
            assert int(computed[k]) == int(row[k]), (row["id"], k, computed[k], row[k])
        got_feat = decide_t_raw_from_features(row, PARAMS)
        assert got_feat == row["expect_T_raw"], (row["id"], got_feat, row["expect_T_raw"])
        seen.add(row["expect_T_raw"])
    assert seen == set(RANK)


def test_rank_signed():
    assert RANK == {"沸": 3, "热": 2, "温": 1, "平": 0, "凉": -1, "寒": -2, "冻": -3}
    assert rank("沸") == 3
    assert rank("平") == 0
    assert rank("冻") == -3
    assert rank("热") - rank("冻") == 5


def test_decide_t_raw_from_features_not_computable():
    base = {
        "P": 110,
        "MA_f": 100,
        "MA_s": 90,
        "slope_f": 0.01,
        "ADX": 30,
        "sign": 1,
        "sigma_pctile": 0.5,
        "ret_pctile": 0.5,
        "computable": False,
    }
    assert decide_t_raw_from_features(base, PARAMS) is None
    missing = dict(base)
    missing["computable"] = True
    missing["ADX"] = ""
    assert decide_t_raw_from_features(missing, PARAMS) is None
    short = {"computable": True, "P": 1}
    assert decide_t_raw_from_features(short, PARAMS) is None
