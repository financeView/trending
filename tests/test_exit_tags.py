"""Exit-tag params load (Task 0) and later assign/digest tests."""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.common import db as dbmod
from scripts.metrics.params import load_params
from scripts.metrics.pipeline import replay_from_ohlc
from tests.test_daily_run_metrics_wire import SHORT_N, _short_params

ROOT = Path(__file__).resolve().parents[1]
METRICS_YAML = ROOT / "config" / "metrics" / "a_share_daily.yaml"

_EXIT_TAG_KEYS = (
    "vol_expand_pctile",
    "champ_k",
    "champ_excess",
    "danger_ret_pctile",
    "danger_amt_pctile",
    "tag_rate_cap",
)


def _yaml_without_key(key: str) -> str:
    lines = METRICS_YAML.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith(f"{key}:")) + "\n"


def test_load_params_requires_exit_tag_thresholds(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(_yaml_without_key("vol_expand_pctile"), encoding="utf-8")
    with pytest.raises((KeyError, ValueError)):
        load_params(p)


def _uptrend_ohlc(n: int) -> list[dict]:
    start = date(2024, 1, 2)
    out: list[dict] = []
    for i in range(n):
        close = 10.0 * (1.015**i)
        d = start + timedelta(days=i)
        out.append(
            {
                "trade_date": d.isoformat(),
                "close_qfq": close,
                "high_qfq": close * 1.02,
                "low_qfq": close * 0.99,
                "open_qfq": close * 0.995,
                "is_st": 0,
                "is_suspended": 0,
            }
        )
    return out


def test_replay_from_ohlc_snap_includes_sigma_pctile():
    """Task 2: replay snaps expose sigma_pctile for vol_expand tagging."""
    params = _short_params()
    min_hist = SHORT_N
    records = _uptrend_ohlc(min_hist + 15)
    snaps = replay_from_ohlc(params, records, min_history=min_hist)
    assert snaps
    asof = snaps[-1]
    assert "sigma_pctile" in asof
    sp = asof.get("sigma_pctile")
    assert sp is not None
    assert math.isfinite(float(sp))


def test_a_share_daily_exit_tag_thresholds():
    params = load_params(METRICS_YAML)
    assert params.param_version == "p05-v3"
    assert params.exit_tags_enabled is False
    assert params.vol_expand_pctile == 0.90
    assert params.champ_k == 3
    assert params.champ_excess == 0.05
    assert params.danger_ret_pctile == 0.05
    assert params.danger_amt_pctile == 0.95
    assert params.tag_rate_cap == 0.02


def test_daily_stock_tags_column_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    conn = dbmod.get_conn(str(db))
    dbmod.init_schema(conn)
    dbmod.upsert_daily_stock(
        conn,
        [
            {
                "trade_date": "2024-01-02",
                "ts_code": "000001.SZ",
                "tags": '["vol_expand"]',
            }
        ],
    )
    row = conn.execute(
        "SELECT tags FROM daily_stock WHERE ts_code=?", ("000001.SZ",)
    ).fetchone()
    assert row[0] == '["vol_expand"]'
    conn.close()


def test_daily_l2_tags_column_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    conn = dbmod.get_conn(str(db))
    dbmod.init_schema(conn)
    dbmod.upsert_daily_l2(
        conn,
        [
            {
                "trade_date": "2024-01-02",
                "code": "801780",
                "tags": '["vol_expand"]',
            }
        ],
    )
    row = conn.execute(
        "SELECT tags FROM daily_l2 WHERE code=?", ("801780",)
    ).fetchone()
    assert row[0] == '["vol_expand"]'
    conn.close()
