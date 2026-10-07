"""L2 daily_run wire: tag ≠ member OR; skip-day NULL engine fields; no L2 events."""
from __future__ import annotations

from datetime import date

from scripts.common.bars import bars_conn
from scripts.daily_run import _l2_asof_row, replay_metrics_cross_section
from tests.test_daily_run_metrics_wire import (
    SHORT_N,
    _seed_uptrend,
    _short_params,
    _weekdays_ending,
)


def test_l2_tag_not_or_of_members():
    # Unit-level _l2_asof_row only — do NOT pass snap=None here (that is skip-day → NULL).
    stock_rows = [
        {"ts_code": "A.SZ", "sw_l2_code": "370100", "tag_warm_to_hot": 0, "amount": 1e8},
        {"ts_code": "B.SZ", "sw_l2_code": "370100", "tag_warm_to_hot": 1, "amount": 2e8},
    ]
    cool_snap = {
        "T": "凉",
        "R": False,
        "tag_warm_to_hot": False,
        "tag_warm_to_flat": False,
        "solar_term": None,
    }
    row = _l2_asof_row(
        "370100",
        ["A.SZ", "B.SZ"],
        stock_rows,
        cool_snap,
        trade_date="2024-01-10",
        members_total=2,
    )
    assert row["tag_warm_to_hot"] == 0  # engine cool — not OR of members
    assert row["warm_to_hot_member_count"] == 1
    assert abs(row["amount"] - 3e8) < 1


def test_l2_skip_day_writes_null_engine_fields():
    stock_rows = [
        {
            "ts_code": "A.SZ",
            "sw_l2_code": "370100",
            "tag_warm_to_hot": 1,
            "amount": 1e8,
            "hard_frozen": 0,
            "_is_suspended": False,
        },
    ]
    row = _l2_asof_row(
        "370100",
        ["A.SZ"],
        stock_rows,
        None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert row["T"] is None and row["right_side"] is None
    assert row["tag_warm_to_hot"] is None  # not 0
    assert "tag_warm_to_hot" in row
    assert row["tag_warm_to_flat"] is None
    assert row["solar_term"] is None
    assert row["warm_to_hot_member_count"] == 1
    assert abs(row["amount"] - 1e8) < 1


def test_l2_events_only_stock_ts_codes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.daily_run.load_metrics_params", lambda: _short_params()
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.common.universe.l2_members_map",
        lambda: {"370100": ["000001.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.l2_members_map",
        lambda: {"370100": ["000001.SZ"]},
    )

    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()

    _stock, l2_rows, _l1, events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ"],
    )
    assert any(r["code"] == "370100" for r in l2_rows)
    assert all(e["ts_code"] == "000001.SZ" for e in events)
    assert not any(e.get("ts_code") == "370100" for e in events)
