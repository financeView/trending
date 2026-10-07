"""Event RS must match daily_stock.RS after peer → backfill → append (no UPDATE)."""
from __future__ import annotations

from datetime import date

from scripts.common.bars import bars_conn
from scripts.common.db import append_signal_events, get_conn, init_schema, upsert_daily_stock
from scripts.daily_run import replay_metrics_cross_section
from tests.test_daily_run_metrics_wire import (
    SHORT_N,
    _seed_uptrend,
    _short_params,
    _weekdays_ending,
)


def test_signal_event_rs_matches_daily(tmp_path, monkeypatch):
    """Offline mini bars: active event RS equals daily_stock.RS (incl. both null)."""
    monkeypatch.setattr("scripts.daily_run.load_quarantine_codes", lambda: set())
    monkeypatch.setattr(
        "scripts.daily_run.l2_members_map",
        lambda: {"370100": ["000001.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.daily_run.stub_l1_members",
        lambda: {"l1_test": ["000001.SZ"]},
    )

    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    bconn = bars_conn(bars_path)
    # ST on asof → EXIT_RIGHT events (same path as test_hard_frozen_and_stage_score).
    _seed_uptrend(bconn, "000001.SZ", dates, is_st=1, start_px=10.0)
    bconn.close()

    stock_rows, _l2, _l1, events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ"],
    )
    assert stock_rows, "expected asof stock row"
    assert events, "expected EXIT (or ENTER) events on ST/uptrend path"

    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    upsert_daily_stock(conn, stock_rows, commit=False)
    append_signal_events(conn, events, commit=False)
    conn.commit()

    daily_rs = conn.execute(
        "SELECT RS FROM daily_stock WHERE ts_code=? AND trade_date=?",
        ("000001.SZ", D.isoformat()),
    ).fetchone()[0]
    # Single-name peer (or RS_raw null under short hist) → both null is OK.
    for ev_rs, in conn.execute(
        """
        SELECT RS FROM signal_event
        WHERE ts_code=? AND trade_date=? AND superseded_by IS NULL
        """,
        ("000001.SZ", D.isoformat()),
    ):
        assert ev_rs == daily_rs
    conn.close()
