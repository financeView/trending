"""Session-asof float_mv spot write (market-data §6); no network."""
import sqlite3

from scripts.common.bars import apply_float_mv_rows, bars_conn


def test_apply_float_mv_rows_upserts(tmp_path):
    path = tmp_path / "bars.db"
    conn = bars_conn(str(path))
    td = "2026-10-14"
    n = apply_float_mv_rows(
        conn,
        td,
        {"000001.SZ": 1.5e11, "600519.SH": -1, "000002.SZ": 2.0e10},
    )
    assert n == 2
    rows = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT ts_code, float_mv FROM bars WHERE trade_date=?", (td,)
        )
    }
    assert rows["000001.SZ"] == 1.5e11
    assert rows["000002.SZ"] == 2.0e10
    assert "600519.SH" not in rows


def test_apply_float_mv_does_not_clobber_ohlc(tmp_path):
    path = tmp_path / "bars.db"
    conn = bars_conn(str(path))
    td = "2026-10-14"
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, close_qfq, amount, bar_source)
        VALUES ('000001.SZ', ?, 10.0, 1e8, 'sina')
        """,
        (td,),
    )
    conn.commit()
    apply_float_mv_rows(conn, td, {"000001.SZ": 9e10})
    row = conn.execute(
        "SELECT close_qfq, amount, float_mv, bar_source FROM bars WHERE ts_code='000001.SZ'"
    ).fetchone()
    assert row == (10.0, 1e8, 9e10, "sina")
