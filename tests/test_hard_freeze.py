# tests/test_hard_freeze.py
from datetime import date, timedelta

from scripts.common.hard_freeze import apply_hard_freeze_flags, load_hard_freeze_min_suspend_days
from scripts.common.bars import bars_conn, ensure_bars_columns
from scripts.common.calendar import load_trade_dates_from_list


def _consec(start: date, n: int) -> list[str]:
    out = []
    d = start
    for _ in range(n):
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_load_n_default():
    assert load_hard_freeze_min_suspend_days() == 20


def test_streak_boundary_n(tmp_path):
    days = _consec(date(2024, 1, 2), 25)
    load_trade_dates_from_list(days)
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    for td in days[:20]:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, td),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=20)
    flags = [
        r[0]
        for r in conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? ORDER BY trade_date",
            (code,),
        )
    ]
    assert flags[:19] == [0] * 19
    assert flags[19] == 1


def test_streak_hole_breaks(tmp_path):
    # calendar has 01-04 but bar row missing → streak must reset
    load_trade_dates_from_list(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    for td in ("2024-01-02", "2024-01-03", "2024-01-05"):
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, td),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=3)
    got = dict(
        conn.execute(
            "SELECT trade_date, hard_freeze_flag FROM bars WHERE ts_code=?",
            (code,),
        )
    )
    assert got == {"2024-01-02": 0, "2024-01-03": 0, "2024-01-05": 0}


def test_missing_flag_source_breaks(tmp_path):
    load_trade_dates_from_list(["2024-01-02", "2024-01-03", "2024-01-04"])
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    rows = [
        ("2024-01-02", 1, "baostock"),
        ("2024-01-03", 1, None),
        ("2024-01-04", 1, "baostock"),
    ]
    for td, sus, src in rows:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,?,?,0)",
            (code, td, sus, src),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=2)
    flags = [
        r[0]
        for r in conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? ORDER BY trade_date",
            (code,),
        )
    ]
    assert flags == [0, 0, 0]


def test_resume_clears(tmp_path):
    load_trade_dates_from_list(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    )
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    for td, sus in [
        ("2024-01-02", 1),
        ("2024-01-03", 1),
        ("2024-01-04", 1),
        ("2024-01-05", 0),
    ]:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,?,?,0)",
            (code, td, sus, "baostock"),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=3)
    got = dict(
        conn.execute(
            "SELECT trade_date, hard_freeze_flag FROM bars WHERE ts_code=? ORDER BY trade_date",
            (code,),
        )
    )
    assert got["2024-01-04"] == 1
    assert got["2024-01-05"] == 0


def test_n_change_requires_rewrite(tmp_path):
    days = _consec(date(2024, 2, 1), 25)
    load_trade_dates_from_list(days)
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000002.SZ"
    for td in days:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, td),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=20)
    asof = days[-1]
    assert (
        conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
            (code, asof),
        ).fetchone()[0]
        == 1
    )
    # Spec §5.2#10 mid-state: yaml N conceptually 60 but no rewrite → flag stays old
    stale = conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
        (code, asof),
    ).fetchone()[0]
    assert stale == 1
    apply_hard_freeze_flags(conn, [code], n=60)
    assert (
        conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
            (code, asof),
        ).fetchone()[0]
        == 0
    )
