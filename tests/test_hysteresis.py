"""§5.3 hysteresis: bootstrap, max_step, exit fast-path, pending (no FSM)."""
from pathlib import Path

from scripts.metrics.hysteresis import Hysteresis, inv_rank, same_side
from scripts.metrics.params import load_params
from scripts.metrics.temp_raw import rank

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_params(ROOT / "config" / "metrics" / "a_share_daily.yaml")


def test_hysteresis_bootstrap_hot_does_not_snap():
    h = Hysteresis(PARAMS)
    t = h.step("热", R=False)
    assert t == "平"
    assert h.T_prev == "平"
    assert h.pending_target == "热"
    assert h.pending_count == 1


def test_hysteresis_max_step_2_climb():
    assert PARAMS.max_step == 2
    h = Hysteresis(PARAMS)
    assert h.step("沸", R=False) == "平"
    # clip 平→沸 (Δ=3) to 热; hysteresis_up=2 confirms 热, not 沸
    assert h.step("沸", R=False) == "热"
    assert h.T_prev == "热"
    assert h.step("沸", R=False) == "热"
    assert h.step("沸", R=False) == "沸"


def test_hysteresis_exit_fast_path_boil_to_flat_one_day():
    assert PARAMS.max_step == 2
    assert PARAMS.hysteresis_down == 1
    h = Hysteresis(PARAMS)
    h.T_prev = "沸"
    h.pending_target = None
    h.pending_count = 0
    t = h.step("冻", R=True)
    assert t == "平"
    assert h.T_prev == "平"
    assert rank(t) <= 0


def test_hysteresis_pending_not_full_keeps_t_prev():
    h = Hysteresis(PARAMS)
    h.T_prev = "平"
    h.pending_target = None
    h.pending_count = 0
    t = h.step("热", R=False)
    assert t == "平"
    assert h.T_prev == "平"
    assert h.pending_target == "热"
    assert h.pending_count == 1
    assert PARAMS.hysteresis_up == 2
    assert h.pending_count < PARAMS.hysteresis_up


def test_hysteresis_null_t_raw_does_not_advance():
    h = Hysteresis(PARAMS)
    h.T_prev = "热"
    h.pending_target = "沸"
    h.pending_count = 1
    assert h.step(None, R=True) is None
    assert h.T_prev == "热"
    assert h.pending_target == "沸"
    assert h.pending_count == 1


def test_hysteresis_null_while_flat_rebootstrap_from_ping():
    """§5.3.1: R=false null stretch clears T_prev; next non-null anchors 平."""
    h = Hysteresis(PARAMS)
    assert h.step("热", R=False) == "平"
    assert h.step("热", R=False) == "热"
    assert h.step(None, R=False) is None
    assert h.T_prev is None
    # Would snap to 热 if old T_prev kept; must re-bootstrap via 平
    assert h.step("热", R=False) == "平"
    assert h.pending_target == "热"
    assert h.pending_count == 1


def test_inv_rank_matches_signed_rank():
    for name in ("沸", "热", "温", "平", "凉", "寒", "冻"):
        assert inv_rank(rank(name)) == name
    assert same_side("热", "沸")
    assert same_side("寒", "冻")
    assert not same_side("热", "寒")


def test_pipeline_trade_day_natural_increments():
    """Consecutive weekdays each get natural +1 (not only calendar gaps)."""
    from scripts.metrics.pipeline import replay_days

    snaps = replay_days(
        PARAMS,
        [
            {"trade_date": "2024-01-05", "T": "热"},  # Fri enter
            {"trade_date": "2024-01-08", "T": "温", "natural_bump_after": 0},  # Mon
            {"trade_date": "2024-01-09", "T": "温"},  # Tue
        ],
    )
    # Fri: 0 → after Fri EOD + weekend gap we only set gap on day0 via OHLC path;
    # here natural_bump_after defaults 0, so Fri after = 1 (trade day only).
    assert snaps[0]["days_natural"] == 0
    assert snaps[0]["days_natural_after_bump"] == 1
    assert snaps[1]["days_natural"] == 1
    assert snaps[1]["days_natural_after_bump"] == 2
    assert snaps[2]["days_natural"] == 2
    assert snaps[2]["days_natural_after_bump"] == 3
