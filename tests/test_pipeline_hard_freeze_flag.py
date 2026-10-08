import datetime as dt

from scripts.common.bars import bars_conn, ensure_bars_columns
from scripts.daily_run import _load_symbol_bars
from scripts.metrics.fsm import (
    EVENT_EXIT,
    EXIT_KIND_UNTRADABLE,
    RightSideFsm,
)
from scripts.metrics.pipeline import bar_hard_frozen


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
