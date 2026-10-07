"""Event RS must match daily_stock.RS after peer → backfill → append (no UPDATE)."""
from __future__ import annotations

from datetime import date

from scripts.common.bars import apply_flag_rows, apply_limit_rows, bars_conn
from scripts.common.db import append_signal_events, get_conn, init_schema, upsert_daily_stock
from scripts.daily_run import replay_metrics_cross_section
from tests.test_daily_run_metrics_wire import (
    SHORT_N,
    _seed_uptrend,
    _short_params,
    _weekdays_ending,
)

# ROC_252 needs index ≥ 252; keep headroom so asof EXIT still has finite RS_raw.
RS_BARS = 260


def _seed_uptrend_then_crash(
    conn,
    ts_code: str,
    dates: list[date],
    *,
    start_px: float = 10.0,
    daily_ret: float = 0.015,
    crash_ret: float = 0.7,
):
    """Uptrend through penultimate bar, one-day crash on asof → temperature EXIT_RIGHT."""
    conn.execute("DELETE FROM bars WHERE ts_code=?", (ts_code,))
    close = start_px
    for i, d in enumerate(dates):
        if i < len(dates) - 1:
            close = start_px * ((1.0 + daily_ret) ** i)
        else:
            close = close * crash_ret
        high = close * 1.02
        low = close * 0.99
        open_ = close * 0.995
        raw = close * 1.1
        conn.execute(
            """
            INSERT INTO bars (
              ts_code, trade_date,
              open_qfq, high_qfq, low_qfq, close_qfq,
              open_raw, high_raw, low_raw, close_raw,
              float_mv, amount, bar_source, is_st, is_suspended
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ts_code,
                d.isoformat(),
                open_,
                high,
                low,
                close,
                raw,
                raw * 1.02,
                raw * 0.99,
                raw,
                1e10,
                1e8,
                "sina",
                0,
                0,
            ),
        )
    td = dates[-1].isoformat()
    apply_flag_rows(conn, [(ts_code, td, 0, 0)])
    apply_limit_rows(conn, td, {ts_code: (raw * 1.1, raw * 0.9)})
    conn.commit()


def _seed_steady_uptrend(
    conn,
    ts_code: str,
    dates: list[date],
    *,
    start_px: float = 20.0,
    daily_ret: float = 0.005,
):
    """Slower constant uptrend peer (different RS_raw vs crash name)."""
    conn.execute("DELETE FROM bars WHERE ts_code=?", (ts_code,))
    for i, d in enumerate(dates):
        close = start_px * ((1.0 + daily_ret) ** i)
        high = close * 1.02
        low = close * 0.99
        open_ = close * 0.995
        raw = close * 1.1
        conn.execute(
            """
            INSERT INTO bars (
              ts_code, trade_date,
              open_qfq, high_qfq, low_qfq, close_qfq,
              open_raw, high_raw, low_raw, close_raw,
              float_mv, amount, bar_source, is_st, is_suspended
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ts_code,
                d.isoformat(),
                open_,
                high,
                low,
                close,
                raw,
                raw * 1.02,
                raw * 0.99,
                raw,
                1e10,
                1e8,
                "sina",
                0,
                0,
            ),
        )
    td = dates[-1].isoformat()
    apply_flag_rows(conn, [(ts_code, td, 0, 0)])
    apply_limit_rows(conn, td, {ts_code: (raw * 1.1, raw * 0.9)})
    conn.commit()


def test_signal_event_rs_matches_daily_both_null(tmp_path, monkeypatch):
    """ST + short hist + single name → daily and event RS both null (null≡null path)."""
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
    assert daily_rs is None
    for (ev_rs,) in conn.execute(
        """
        SELECT RS FROM signal_event
        WHERE ts_code=? AND trade_date=? AND superseded_by IS NULL
        """,
        ("000001.SZ", D.isoformat()),
    ):
        assert ev_rs is None
        assert ev_rs == daily_rs
    conn.close()


def test_signal_event_rs_matches_daily_nonnull(tmp_path, monkeypatch):
    """Two eligible peers + finite RS_raw + asof EXIT → event RS is peer int 0|100."""
    monkeypatch.setattr("scripts.daily_run.load_quarantine_codes", lambda: set())
    monkeypatch.setattr(
        "scripts.daily_run.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.daily_run.stub_l1_members",
        lambda: {"l1_test": ["000001.SZ", "000002.SZ"]},
    )

    D = date(2024, 12, 31)
    dates = _weekdays_ending(D, RS_BARS)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    bconn = bars_conn(bars_path)
    _seed_uptrend_then_crash(bconn, "000001.SZ", dates, start_px=10.0)
    _seed_steady_uptrend(bconn, "000002.SZ", dates, start_px=20.0, daily_ret=0.005)
    bconn.close()

    stock_rows, _l2, _l1, events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ", "000002.SZ"],
    )
    assert stock_rows
    asof_events = [
        e
        for e in events
        if e["ts_code"] == "000001.SZ" and e["trade_date"] == D.isoformat()
    ]
    assert asof_events, "expected asof EXIT_RIGHT on crash name"
    assert any(e["event"] == "EXIT_RIGHT" for e in asof_events)
    # Backfill must set peer int before append (removing the memory step fails here).
    for e in asof_events:
        assert isinstance(e.get("RS"), int) and e["RS"] in (0, 100)

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
    # SQLite may surface REAL; value must still be whole 0 or 100.
    assert daily_rs in (0, 100)
    assert int(daily_rs) == daily_rs

    ev_rows = conn.execute(
        """
        SELECT RS FROM signal_event
        WHERE ts_code=? AND trade_date=? AND superseded_by IS NULL
        """,
        ("000001.SZ", D.isoformat()),
    ).fetchall()
    assert ev_rows
    for (ev_rs,) in ev_rows:
        assert ev_rs == daily_rs
        assert ev_rs in (0, 100)
        assert int(ev_rs) == ev_rs
    conn.close()
