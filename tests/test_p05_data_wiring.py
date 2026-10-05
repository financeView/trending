"""P0.5 data-wiring：flags / limits / coverage（离线夹具，无网络）。"""
from __future__ import annotations

from datetime import date, timedelta

from scripts.common.bars import (
    FLAG_SOURCE_BAOSTOCK,
    LIMIT_SOURCE_EM,
    apply_flag_rows,
    apply_limit_rows,
    bars_conn,
)
from scripts.common.coverage import compute_coverage_from_bars, evaluate_ok
from scripts.common.universe import members_tradable


def _seed_ohlc(conn, ts_code: str, trade_date: str, *, n_history: int = 1):
    """写入 trade_date 起向前 n_history 个自然日的完整 OHLC（计数用）。"""
    base = date.fromisoformat(trade_date)
    conn.execute("DELETE FROM bars WHERE ts_code=?", (ts_code,))
    for i in range(n_history):
        d = (base - timedelta(days=n_history - 1 - i)).isoformat()
        conn.execute(
            """
            INSERT INTO bars (
              ts_code, trade_date,
              open_qfq, high_qfq, low_qfq, close_qfq,
              open_raw, high_raw, low_raw, close_raw,
              bar_source
            ) VALUES (?,?, 10,11,9,10.5, 11,12,10,11.2, 'sina')
            """,
            (ts_code, d),
        )
    conn.commit()


def test_apply_baostock_flags_offline(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    _seed_ohlc(conn, "000001.SZ", "2024-01-05")
    n = apply_flag_rows(
        conn,
        [
            ("000001.SZ", "2024-01-05", 0, 0),
            ("000002.SZ", "2024-01-05", 1, 0),
            ("600000.SH", "2024-01-05", 0, 1),
        ],
    )
    assert n == 3
    row = conn.execute(
        "SELECT is_suspended, is_st, flag_source FROM bars "
        "WHERE ts_code='000001.SZ' AND trade_date='2024-01-05'"
    ).fetchone()
    assert row == (0, 0, FLAG_SOURCE_BAOSTOCK)
    ohlc = conn.execute(
        "SELECT open_raw, close_qfq FROM bars WHERE ts_code='000001.SZ' "
        "AND trade_date='2024-01-05'"
    ).fetchone()
    assert ohlc == (11.0, 10.5)
    conn.close()


def test_apply_em_limits_offline(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    _seed_ohlc(conn, "600519.SH", "2024-01-10")
    apply_flag_rows(conn, [("600519.SH", "2024-01-10", 0, 0)])
    n = apply_limit_rows(
        conn,
        "2024-01-10",
        {"600519.SH": (1800.0, 1472.0)},
    )
    assert n == 1
    row = conn.execute(
        "SELECT limit_up, limit_down, limit_source FROM bars "
        "WHERE ts_code='600519.SH' AND trade_date='2024-01-10'"
    ).fetchone()
    assert row == (1800.0, 1472.0, LIMIT_SOURCE_EM)
    conn.close()


def test_ohlc_upsert_preserves_flags_and_limits(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    apply_flag_rows(conn, [("000001.SZ", "2024-01-05", 0, 1)])
    apply_limit_rows(conn, "2024-01-05", {"000001.SZ": (11.0, 9.0)})
    from scripts.common.bars import _OHLC_UPSERT

    conn.execute(
        _OHLC_UPSERT,
        (
            "000001.SZ",
            "2024-01-05",
            1,
            2,
            0.5,
            1.5,
            1.1,
            2.1,
            0.6,
            1.6,
            100,
            200,
            "sina",
            "2024-01-05T12:00:00Z",
        ),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT is_st, is_suspended, flag_source, limit_up, limit_down, limit_source,
               open_qfq, open_raw
        FROM bars WHERE ts_code='000001.SZ'
        """
    ).fetchone()
    assert row[0] == 1 and row[1] == 0 and row[2] == FLAG_SOURCE_BAOSTOCK
    assert row[3] == 11.0 and row[4] == 9.0 and row[5] == LIMIT_SOURCE_EM
    assert row[6] == 1.0 and row[7] == 1.1
    conn.close()


def test_source_mix_forbidden(tmp_path):
    import pytest
    from scripts.common.bars import _assert_source_not_mixed

    conn = bars_conn(str(tmp_path / "bars.db"))
    conn.execute(
        "INSERT INTO sync_meta (ts_code, preferred_source) VALUES ('000001.SZ','sina')"
    )
    conn.commit()
    with pytest.raises(ValueError, match="mix forbidden"):
        _assert_source_not_mixed(conn, "000001.SZ", "em")
    _assert_source_not_mixed(conn, "000001.SZ", "sina")
    conn.close()


def test_members_tradable_excludes_st_suspend(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    td = date(2024, 1, 5)
    universe = ["000001.SZ", "000002.SZ", "600000.SH", "600519.SH"]
    for code, sus, st in [
        ("000001.SZ", 0, 0),
        ("000002.SZ", 1, 0),
        ("600000.SH", 0, 1),
    ]:
        _seed_ohlc(conn, code, td.isoformat())
        apply_flag_rows(conn, [(code, td.isoformat(), sus, st)])
    _seed_ohlc(conn, "600519.SH", td.isoformat())
    U = members_tradable(conn, td, universe=universe, quarantine=[])
    assert U == ["000001.SZ"]
    conn.close()


def test_compute_coverage_from_bars_fixture(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    td = date(2024, 1, 10)
    universe = ["000001.SZ", "000002.SZ", "600000.SH"]
    for code in universe:
        _seed_ohlc(conn, code, td.isoformat(), n_history=1)
        apply_flag_rows(conn, [(code, td.isoformat(), 0, 0)])
    apply_limit_rows(
        conn,
        td.isoformat(),
        {"000001.SZ": (12.0, 10.0), "000002.SZ": (13.0, 11.0)},
    )
    _seed_ohlc(conn, "000001.SZ", td.isoformat(), n_history=5)
    apply_flag_rows(conn, [("000001.SZ", td.isoformat(), 0, 0)])
    apply_limit_rows(conn, td.isoformat(), {"000001.SZ": (12.0, 10.0)})

    m = compute_coverage_from_bars(
        conn, td, universe=universe, quarantine=[], min_history=5
    )
    assert m.tradable_count == 3
    assert m.bar_coverage == 1.0
    assert abs(m.limit_coverage_asof - 2.0 / 3.0) < 1e-9
    assert abs(m.computable_coverage - 1.0 / 3.0) < 1e-9
    assert m.open_raw_coverage_asof == 1.0
    conn.close()


def test_process_day_uses_real_coverage(tmp_path, monkeypatch):
    from scripts.common import coverage as cov
    from scripts.daily_run import process_day

    monkeypatch.setattr(cov, "DEFAULT_MIN_HISTORY", 3)
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    td = date(2024, 1, 10)
    for code in ["000001.SZ", "600519.SH"]:
        _seed_ohlc(conn, code, td.isoformat(), n_history=3)
        apply_flag_rows(conn, [(code, td.isoformat(), 0, 0)])
        apply_limit_rows(conn, td.isoformat(), {code: (20.0, 16.0)})
    conn.close()

    uni = tmp_path / "uni.yaml"
    uni.write_text(
        "map_version: p05-v1\nmembers:\n  - 000001.SZ\n  - 600519.SH\nquarantine: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNIVERSE_YAML", str(uni))

    st = process_day(td, td, bars_path=bars_path)
    assert st == "ok"

    bconn = bars_conn(bars_path)
    bconn.execute("UPDATE bars SET limit_up=NULL, limit_down=NULL, limit_source=NULL")
    bconn.commit()
    bconn.close()
    st2 = process_day(td, td, bars_path=bars_path)
    assert st2 == "partial"


def test_stub_coverage_flag(tmp_path, monkeypatch):
    from scripts.daily_run import process_day

    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    uni = tmp_path / "uni.yaml"
    uni.write_text(
        "map_version: p05-v1\nmembers:\n  - 000001.SZ\nquarantine: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNIVERSE_YAML", str(uni))
    st = process_day(date(2024, 1, 10), date(2024, 1, 10), stub_coverage=True)
    assert st == "ok"


def test_history_day_low_limit_still_ok_via_compute(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    D = date(2024, 1, 5)
    asof = date(2024, 1, 10)
    universe = ["000001.SZ"]
    _seed_ohlc(conn, "000001.SZ", D.isoformat(), n_history=3)
    apply_flag_rows(conn, [("000001.SZ", D.isoformat(), 0, 0)])
    m = compute_coverage_from_bars(
        conn, D, universe=universe, quarantine=[], min_history=3
    )
    assert m.limit_coverage_asof == 0.0
    d = evaluate_ok(D, asof, m, computable_min=0.5)
    assert d.ok
    conn.close()
