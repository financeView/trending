"""Minimal §6 FSM tests (full named fixture suite is Task 6)."""
from scripts.metrics.fsm import (
    EVENT_ENTER,
    EVENT_EXIT,
    EVENT_WARM_TO_HOT,
    EXIT_KIND_TEMPERATURE,
    EXIT_KIND_UNTRADABLE,
    SOLAR_GRAIN_RAIN,
    SOLAR_LIQIU,
    RightSideFsm,
)


def test_enter_hot_no_warm_to_hot_event():
    fsm = RightSideFsm()
    events = fsm.step_trade_day("热")
    assert fsm.R is True
    assert fsm.right_side_days_trading == 0
    assert fsm.right_side_days_natural == 0
    assert fsm.tag_warm_to_hot is True
    assert fsm.solar_term == SOLAR_GRAIN_RAIN
    assert fsm.stage_score == 0.0
    assert fsm.stage_score_raw == 0.0
    assert [e["event"] for e in events] == [EVENT_ENTER]
    assert EVENT_WARM_TO_HOT not in {e["event"] for e in events}
    assert events[0]["T"] == "热"
    assert events[0]["detail"] == {}


def test_enter_boil_no_warm_to_hot_event():
    fsm = RightSideFsm()
    events = fsm.step_trade_day("沸")
    assert fsm.R is True
    assert fsm.tag_warm_to_hot is True
    assert [e["event"] for e in events] == [EVENT_ENTER]
    assert EVENT_WARM_TO_HOT not in {e["event"] for e in events}


def test_hard_frozen_st_sets_tag_warm_to_flat():
    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    events = fsm.step_trade_day("热", hard_frozen=True)
    assert fsm.R is False
    assert fsm.tag_warm_to_flat is True
    assert fsm.tag_warm_to_hot is False
    assert fsm.solar_term == SOLAR_LIQIU
    assert fsm.stage_score is None
    assert fsm.stage_score_raw is None
    assert fsm.just_exited_today is True
    assert fsm.right_side_days_trading == 0
    assert [e["event"] for e in events] == [EVENT_EXIT]
    assert events[0]["detail"]["exit_kind"] == EXIT_KIND_UNTRADABLE
    # same day: no temperature re-enter
    assert EVENT_ENTER not in {e["event"] for e in events}


def test_hard_frozen_no_same_day_enter_even_if_hot():
    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    fsm.step_trade_day("热", hard_frozen=True)
    assert fsm.R is False
    events = fsm.step_trade_day("热", hard_frozen=True)
    assert fsm.R is False
    assert events == []


def test_no_enter_warm():
    fsm = RightSideFsm()
    for _ in range(10):
        events = fsm.step_trade_day("温")
        assert fsm.R is False
        assert events == []
        assert fsm.tag_warm_to_hot is False
        assert fsm.solar_term is None


def test_reconfirm_warm_to_hot_only():
    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    fsm.step_trade_day("温")
    assert fsm.R is True
    assert fsm.right_side_days_trading == 1
    events = fsm.step_trade_day("热")
    assert fsm.R is True
    assert fsm.tag_warm_to_hot is True
    assert fsm.right_side_days_trading == 2
    assert [e["event"] for e in events] == [EVENT_WARM_TO_HOT]
    assert EVENT_ENTER not in {e["event"] for e in events}


def test_temperature_exit_warm_to_flat():
    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    events = fsm.step_trade_day("平")
    assert fsm.R is False
    assert fsm.tag_warm_to_flat is True
    assert fsm.solar_term == SOLAR_LIQIU
    assert fsm.stage_score is None
    assert events[0]["event"] == EVENT_EXIT
    assert events[0]["detail"]["exit_kind"] == EXIT_KIND_TEMPERATURE


def test_soft_null_in_r_fills_last_valid():
    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    events = fsm.step_trade_day(None, hard_frozen=False)
    assert fsm.R is True
    assert fsm.T_fsm == "热"
    assert fsm.T_filled is True
    assert fsm.solar_term != SOLAR_LIQIU
    assert events == []


def test_null_not_r_skips_even_if_last_was_hot():
    fsm = RightSideFsm()
    fsm.T_last_valid = "热"
    events = fsm.step_trade_day(None)
    assert fsm.R is False
    assert events == []
    events = fsm.step_trade_day("温")
    assert fsm.R is False
    assert events == []


def test_fsm_fri_mon_natural_day_bump():
    fsm = RightSideFsm()
    fsm.step_trade_day("热")  # Friday enter
    assert fsm.right_side_days_trading == 0
    fsm.bump_natural_days(1)  # Fri EOD (§6.3)
    fsm.bump_natural_days(2)  # Sat + Sun
    assert fsm.right_side_days_natural == 3
    fsm.step_trade_day("温")  # Monday persist
    assert fsm.R is True
    assert fsm.right_side_days_trading == 1
    fsm.bump_natural_days(1)  # Mon EOD
    assert fsm.right_side_days_natural == 4


def test_bump_skipped_after_exit():
    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    fsm.step_trade_day("平")
    fsm.bump_natural_days(2)
    assert fsm.right_side_days_natural == 0
