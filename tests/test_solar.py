"""Minimal §8.2 solar linear scorer tests (full §8.9 suite is Task 6)."""
from pathlib import Path

import math
import pytest

from scripts.metrics.params import load_params
from scripts.metrics.solar import piecewise_linear_clamp, step_solar

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_params(ROOT / "config" / "metrics" / "a_share_daily.yaml")


def test_piecewise_linear_clamp_no_extrapolate():
    knots = PARAMS.knots_g
    assert piecewise_linear_clamp(0.0, knots) == 0.0
    assert piecewise_linear_clamp(0.5, knots) == 0.25
    assert piecewise_linear_clamp(5.0, knots) == 1.0
    assert piecewise_linear_clamp(-1.0, knots) == 0.0
    assert piecewise_linear_clamp(6.0, knots) == 1.0
    mid = piecewise_linear_clamp(1.0, knots)
    assert mid == pytest.approx(0.40)
    assert math.isfinite(mid)


def test_enter_day_high_sigma_still_grain_rain_score_0():
    out = step_solar(
        PARAMS,
        None,
        entered_today=True,
        right_side=True,
        days_trading=0,
        P_t=100.0,
        sigma_pctile=0.99,
        atr_pct=0.02,
    )
    assert out.solar_term == "谷雨"
    assert out.stage_score == 0
    assert out.stage_score_raw == 0
    assert out.stage_score_peak == 0
    assert out.v_raw is None


def test_exit_day_scores_is_none():
    entered = step_solar(
        PARAMS,
        None,
        entered_today=True,
        right_side=True,
        days_trading=0,
        P_t=100.0,
        sigma_pctile=0.5,
        atr_pct=0.02,
    )
    out = step_solar(
        PARAMS,
        entered,
        exited_today=True,
        right_side=False,
        days_trading=0,
        P_t=100.0,
        sigma_pctile=0.5,
        atr_pct=0.02,
    )
    assert out.solar_term == "立秋"
    assert out.stage_score is None
    assert out.stage_score_raw is None
    assert out.stage_score != 0


def test_drawdown_does_not_retreat_peak():
    entered = step_solar(
        PARAMS,
        None,
        entered_today=True,
        right_side=True,
        days_trading=0,
        P_t=100.0,
        sigma_pctile=0.5,
        atr_pct=0.02,
    )
    # g_raw = ln(1.10517)/0.02 ≈ 5 → g clamp 1.0 → peak ≥ 小暑 cut
    spiked = step_solar(
        PARAMS,
        entered,
        right_side=True,
        days_trading=1,
        P_t=110.517,
        sigma_pctile=0.5,
        atr_pct=0.02,
    )
    assert spiked.solar_term == "小暑"
    peak = spiked.stage_score_peak
    dd = step_solar(
        PARAMS,
        spiked,
        right_side=True,
        days_trading=2,
        P_t=50.0,
        sigma_pctile=0.2,
        atr_pct=0.02,
    )
    assert dd.g_raw_eff == 0
    assert dd.g_raw < 0
    assert dd.stage_score_peak == peak
    assert dd.solar_term == "小暑"
    assert dd.solar_term != "夏至"


def test_C3_reject_solar_entry_gate(tmp_path):
    src = (ROOT / "config" / "metrics" / "a_share_daily.yaml").read_text(encoding="utf-8")
    bad = tmp_path / "gated.yaml"
    bad.write_text(src + "\nrequire_solar_term_for_entry: 谷雨\n", encoding="utf-8")
    with pytest.raises(ValueError, match="require_solar_term_for_entry"):
        load_params(bad)
