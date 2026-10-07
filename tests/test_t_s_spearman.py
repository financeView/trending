"""Spec C Spearman gates: synthetic replay + gold CSV (live waived)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from scripts.metrics.params import load_params
from scripts.metrics.pipeline import replay_from_ohlc
from scripts.metrics.s_temp import compute_s_temp
from scripts.metrics.spearman import spearman_corr
from scripts.metrics.temp_raw import rank

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_params(ROOT / "config" / "metrics" / "a_share_daily.yaml")
GOLD = ROOT / "fixtures" / "temp_raw_gold.csv"


def _uptrend_records(n: int) -> list[dict]:
    """Steady monotonic uptrend OHLC spine (growth tuned for T/S_temp Spearman)."""
    start = date(2020, 1, 2)
    out: list[dict] = []
    for i in range(n):
        close = 10.0 * (1.0 + 0.005) ** i
        d = start + timedelta(days=i)
        out.append(
            {
                "trade_date": d.isoformat(),
                "close_qfq": close,
                "high_qfq": close * 1.01,
                "low_qfq": close * 0.99,
                "is_st": 0,
                "is_suspended": 0,
            }
        )
    return out


def test_spearman_synthetic_uptrend_post_hysteresis_t():
    n = max(PARAMS.min_history_temp, 60)
    snaps = replay_from_ohlc(PARAMS, _uptrend_records(n + 20), min_history=n)
    ranks: list[float] = []
    scores: list[float] = []
    for snap in snaps:
        t = snap.get("T")
        s = snap.get("S_temp")
        if t is None or s is None:
            continue
        ranks.append(float(rank(t)))
        scores.append(float(s))
    assert len(ranks) >= 10
    corr = spearman_corr(ranks, scores)
    assert corr is not None
    assert corr >= PARAMS.spearman_min


def test_spearman_gold_csv_t_raw_standin():
    df = pd.read_csv(GOLD)
    ranks: list[float] = []
    scores: list[float] = []
    for _, row in df.iterrows():
        feats = row.to_dict()
        if "slope_s" not in feats or feats.get("slope_s") is None or (
            isinstance(feats.get("slope_s"), float) and feats["slope_s"] != feats["slope_s"]
        ):
            feats["slope_s"] = feats["slope_f"]
        t_raw = feats.get("expect_T_raw")
        s = compute_s_temp(feats, t_raw, PARAMS)
        if s is None:
            continue
        ranks.append(float(rank(str(t_raw))))
        scores.append(float(s))
    assert len(ranks) >= 5
    corr = spearman_corr(ranks, scores)
    assert corr is not None
    assert corr >= PARAMS.spearman_min
