import datetime as dt
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from scripts.common.bars import bars_conn, ensure_bars_columns
from scripts.common.calendar import load_trade_dates_from_list
from scripts.common.hard_freeze import apply_hard_freeze_flags
from scripts.daily_run import _load_symbol_bars
from scripts.metrics.fsm import (
    EVENT_EXIT,
    EXIT_KIND_UNTRADABLE,
    RightSideFsm,
)
from scripts.metrics.params import load_params
from scripts.metrics.pipeline import bar_hard_frozen, replay_from_ohlc


def test_bar_hard_frozen_or():
    assert bar_hard_frozen({"is_st": 0, "hard_freeze_flag": 1}) is True
    assert bar_hard_frozen({"is_st": 1, "hard_freeze_flag": 0}) is True
    assert bar_hard_frozen({"is_st": 0, "hard_freeze_flag": 0}) is False


def test_hard_freeze_flag_forces_exit_untradable():
    """Spec §5.2#5: flag set + R → EXIT_RIGHT / forced_exit_untradable."""
    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    events = fsm.step_trade_day(
        "热",
        hard_frozen=bar_hard_frozen({"is_st": 0, "hard_freeze_flag": 1}),
    )
    assert fsm.R is False
    assert [e["event"] for e in events] == [EVENT_EXIT]
    assert events[0]["detail"]["exit_kind"] == EXIT_KIND_UNTRADABLE


def test_streak_n_minus_1_no_forced_exit(tmp_path):
    """Spec §5.2#5: streak=N−1 → flag=0 → in R 无 forced_exit."""
    days = []
    d = date(2024, 1, 2)
    for _ in range(19):
        days.append(d.isoformat())
        d += timedelta(days=1)
    load_trade_dates_from_list(days)
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    for td in days:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, td),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=20)
    flag = conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
        (code, days[-1]),
    ).fetchone()[0]
    assert flag == 0

    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    assert fsm.R is True
    events = fsm.step_trade_day(
        "热",
        hard_frozen=bar_hard_frozen({"is_st": 0, "hard_freeze_flag": flag}),
    )
    assert fsm.R is True
    assert not any(e["event"] == EVENT_EXIT for e in events)


def test_load_symbol_bars_includes_flag(tmp_path):
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    ensure_bars_columns(conn)
    conn.execute(
        """
        INSERT INTO bars (
          ts_code, trade_date, open_qfq, high_qfq, low_qfq, close_qfq,
          is_st, is_suspended, hard_freeze_flag
        ) VALUES ('000001.SZ','2024-01-08',1,1,1,1,0,0,1)
        """
    )
    conn.commit()
    rows = _load_symbol_bars(conn, "000001.SZ", dt.date(2024, 1, 8))
    assert rows and int(rows[-1]["hard_freeze_flag"]) == 1


def test_replay_from_ohlc_ors_hard_freeze_flag():
    """replay_from_ohlc snap.hard_frozen follows is_st ∨ hard_freeze_flag."""
    root = Path(__file__).resolve().parents[1]
    params = replace(
        load_params(root / "config" / "metrics" / "a_share_daily.yaml"),
        vol_hist=40,
        ma_slow=10,
        ma_fast=5,
        slope_n=3,
        adx_len=5,
        atr_len=5,
        vol_lookback=8,
        ret_k=5,
    )
    n = 40
    records = []
    start = date(2024, 1, 2)
    for i in range(n + 5):
        close = 10.0 * (1.005**i)
        d = start + timedelta(days=i)
        records.append(
            {
                "trade_date": d.isoformat(),
                "close_qfq": close,
                "high_qfq": close * 1.01,
                "low_qfq": close * 0.99,
                "is_st": 0,
                "is_suspended": 0,
                "hard_freeze_flag": 1 if i == n + 4 else 0,
            }
        )
    snaps = replay_from_ohlc(params, records, min_history=n)
    assert snaps
    assert snaps[-1]["hard_frozen"] is True
    assert snaps[-2]["hard_frozen"] is False
