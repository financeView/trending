from datetime import date

from scripts.common.bars import bars_conn, LIMIT_SOURCE_BOARD_CALC, LIMIT_SOURCE_EM
from scripts.common.board_calc import board_pct, limit_prices, apply_board_calc
from scripts.common.calendar import load_trade_dates_from_list


def test_board_pct_st_priority_and_prefixes():
    assert board_pct("300001.SZ", 1) == 0.05
    assert board_pct("301001.SZ", 0) == 0.20
    assert board_pct("688001.SH", 0) == 0.20
    assert board_pct("600000.SH", 0) == 0.10


def test_half_up_not_bankers():
    # 1.15 * 1.1 = 1.265 → HALF_UP 1.27; Python round → 1.26
    up, down = limit_prices(1.15, 0.10)
    assert up == 1.27
    assert round(1.15 * 1.1, 2) == 1.26  # document divergence


def test_hist_fill_and_asof_skip(tmp_path):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "600000.SH"
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw, is_st, flag_source)"
        " VALUES (?,?,?,?, 'baostock')",
        (code, "2024-01-05", 10.0, 0),
    )
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw, is_st, flag_source)"
        " VALUES (?,?,?,?, 'baostock')",
        (code, "2024-01-08", 10.5, 0),
    )
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw, is_st, flag_source)"
        " VALUES (?,?,?,?, 'baostock')",
        (code, "2024-01-09", 10.6, 0),
    )
    conn.commit()
    asof = date(2024, 1, 9)
    n = apply_board_calc(conn, [code], session_asof=asof, limit_rule="board_calc_v1")
    assert n >= 1
    hist = conn.execute(
        "SELECT limit_up, limit_down, limit_source, preclose_raw FROM bars"
        " WHERE ts_code=? AND trade_date='2024-01-08'",
        (code,),
    ).fetchone()
    assert hist[2] == LIMIT_SOURCE_BOARD_CALC
    assert hist[3] == 10.0
    assert hist[0] == 11.0 and hist[1] == 9.0
    asof_row = conn.execute(
        "SELECT limit_up, limit_source FROM bars WHERE ts_code=? AND trade_date='2024-01-09'",
        (code,),
    ).fetchone()
    assert asof_row[0] is None and asof_row[1] is None


def test_no_overwrite_vendor(tmp_path):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "600000.SH"
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw) VALUES (?,?,?)",
        (code, "2024-01-05", 10.0),
    )
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw, limit_up, limit_down, limit_source)"
        " VALUES (?,?,?,?,?,?)",
        (code, "2024-01-08", 10.5, 12.0, 8.0, LIMIT_SOURCE_EM),
    )
    conn.commit()
    apply_board_calc(
        conn, [code], session_asof=date(2024, 1, 9), limit_rule="board_calc_v1"
    )
    up, src = conn.execute(
        "SELECT limit_up, limit_source FROM bars WHERE trade_date='2024-01-08'"
    ).fetchone()
    assert up == 12.0 and src == LIMIT_SOURCE_EM


def test_limit_rule_gate(tmp_path):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "600000.SH"
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw) VALUES (?,?,?)",
        (code, "2024-01-05", 10.0),
    )
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw) VALUES (?,?,?)",
        (code, "2024-01-08", 10.5),
    )
    conn.commit()
    apply_board_calc(
        conn, [code], session_asof=date(2024, 1, 9), limit_rule="vendor_fields"
    )
    assert conn.execute(
        "SELECT limit_up FROM bars WHERE trade_date='2024-01-08'"
    ).fetchone()[0] is None


def test_session_asof_not_end(tmp_path):
    """--end historical day must still board_calc when session_asof is newer."""
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "600000.SH"
    for td, px in [("2024-01-05", 10.0), ("2024-01-08", 10.5)]:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, close_raw) VALUES (?,?,?)",
            (code, td, px),
        )
    conn.commit()
    apply_board_calc(
        conn, [code], session_asof=date(2024, 1, 9), limit_rule="board_calc_v1"
    )
    assert conn.execute(
        "SELECT limit_source FROM bars WHERE trade_date='2024-01-08'"
    ).fetchone()[0] == LIMIT_SOURCE_BOARD_CALC
