import json

from scripts.common.bars import bars_conn
from scripts.common.calendar import load_trade_dates_from_list
from scripts.common.db import consumed_signal_sides, get_conn, init_schema
from scripts.eval.live_shadow_step import live_allowed, main, run_asof


def _meta(conn, day, status="ok", param="p-T", mmap="m-T"):
    conn.execute(
        """
        INSERT INTO run_meta (
          trade_date, status, param_version, map_version,
          bar_coverage, computable_coverage, limit_coverage_asof, tradable_count
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (day, status, param, mmap, 1, 1, 1, 5),
    )


def _event(conn, day, ts, event, eid=None):
    conn.execute(
        """
        INSERT INTO signal_event (id, trade_date, ts_code, event, T, RS, detail)
        VALUES (?,?,?,?,?,?,?)
        """,
        (eid, day, ts, event, "hot", 1.0, json.dumps({"exit_kind": "temperature"})),
    )


def _bar_row(conn, ts, day, *, limits=True, open_raw=10.0, down=9.0, up=11.0, suspended=0):
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, open_raw, close_raw, limit_up, limit_down, is_suspended)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            ts,
            day,
            open_raw,
            open_raw,
            up if limits else None,
            down if limits else None,
            suspended,
        ),
    )


def test_live_skips_when_run_meta_not_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-08", status="partial")
    conn.commit()
    ok, why = live_allowed(conn, "2024-01-08", None)
    assert ok is False and why == "partial"
    conn.close()
    rc = main(["--asof", "2024-01-08", "--db", str(tmp_path / "trend.db"), "--dry-run"])
    assert rc == 0


def test_live_allows_ok(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05")
    _meta(conn, "2024-01-08")
    conn.commit()
    ok, why = live_allowed(conn, "2024-01-08", "2024-01-05")
    assert ok is True and why == "ok"
    ok, why = live_allowed(conn, "2024-01-08", "2024-01-04")
    assert ok is True and why == "ok"
    conn.close()


def test_live_skips_asof_not_on_calendar(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-08"])
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-09")
    conn.commit()
    conn.close()
    assert run_asof("2024-01-09", db_path=str(tmp_path / "trend.db")) == 0
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0]
    conn.close()
    assert n == 0


def test_live_skips_confirm_not_ok(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05", "partial")
    _meta(conn, "2024-01-08", "ok")
    conn.commit()
    ok, why = live_allowed(conn, "2024-01-08", "2024-01-05")
    assert ok is False and why == "confirm_not_ok"
    conn.close()


def test_live_skips_missing_bars_does_not_consume(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    db = tmp_path / "trend.db"
    bars = tmp_path / "bars.db"
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05")
    _meta(conn, "2024-01-08")
    _event(conn, "2024-01-05", "000001.SZ", "ENTER_RIGHT", eid=1)
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    bconn.close()
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 0
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0] == 0
    assert consumed_signal_sides(conn) == set()
    conn.close()


def test_param_version_copied_from_confirm_day(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    db = tmp_path / "trend.db"
    bars = tmp_path / "bars.db"
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05", param="p-confirm", mmap="m-confirm")
    _meta(conn, "2024-01-08", param="p-T", mmap="m-T")
    _event(conn, "2024-01-05", "000001.SZ", "ENTER_RIGHT", eid=1)
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    _bar_row(bconn, "000001.SZ", "2024-01-08")
    bconn.commit()
    bconn.close()
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 0
    conn = get_conn()
    row = conn.execute("SELECT param_version, map_version FROM paper_fill").fetchone()
    assert row == ("p-confirm", "m-confirm")
    conn.close()


def test_second_asof_does_not_duplicate_consumed(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    db = tmp_path / "trend.db"
    bars = tmp_path / "bars.db"
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05")
    _meta(conn, "2024-01-08")
    _event(conn, "2024-01-05", "000001.SZ", "ENTER_RIGHT", eid=1)
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    _bar_row(bconn, "000001.SZ", "2024-01-08")
    bconn.commit()
    bconn.close()
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 0
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 0
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0]
    assert n == 1
    conn.close()


def test_from_heartbeat_walks_all_ok_days(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    db = tmp_path / "trend.db"
    bars = tmp_path / "bars.db"
    hb = tmp_path / "heartbeat.json"
    hb.write_text(
        json.dumps({"status": "ok", "days": ["2024-01-08", "2024-01-09"], "asof": "2024-01-09"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05")
    _meta(conn, "2024-01-08")
    _meta(conn, "2024-01-09")
    _event(conn, "2024-01-05", "000001.SZ", "ENTER_RIGHT", eid=1)
    _event(conn, "2024-01-08", "000002.SZ", "ENTER_RIGHT", eid=2)
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    _bar_row(bconn, "000001.SZ", "2024-01-08")
    _bar_row(bconn, "000002.SZ", "2024-01-08")
    _bar_row(bconn, "000001.SZ", "2024-01-09")
    _bar_row(bconn, "000002.SZ", "2024-01-09")
    bconn.commit()
    bconn.close()
    rc = main(
        [
            "--from-heartbeat",
            "--db",
            str(db),
            "--bars-db",
            str(bars),
            "--heartbeat",
            str(hb),
        ]
    )
    assert rc == 0
    conn = get_conn()
    codes = {r[0] for r in conn.execute("SELECT ts_code FROM paper_fill WHERE status='filled'")}
    assert codes == {"000001.SZ", "000002.SZ"}
    conn.close()


def test_catchup_day_without_limits_does_not_data_gap_consume(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    db = tmp_path / "trend.db"
    bars = tmp_path / "bars.db"
    hb = tmp_path / "heartbeat.json"
    hb.write_text(
        json.dumps({"status": "ok", "days": ["2024-01-08", "2024-01-09"], "asof": "2024-01-09"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05")
    _meta(conn, "2024-01-08")
    _meta(conn, "2024-01-09")
    _event(conn, "2024-01-05", "000001.SZ", "ENTER_RIGHT", eid=1)
    _event(conn, "2024-01-08", "000002.SZ", "ENTER_RIGHT", eid=2)
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    _bar_row(bconn, "000001.SZ", "2024-01-08", limits=False)
    _bar_row(bconn, "000002.SZ", "2024-01-09")
    bconn.commit()
    bconn.close()
    assert main(["--from-heartbeat", "--db", str(db), "--bars-db", str(bars), "--heartbeat", str(hb)]) == 0
    conn = get_conn()
    rows = list(conn.execute("SELECT ts_code, status FROM paper_fill"))
    assert ("000001.SZ", "data_gap") not in rows
    assert (1, "buy") not in consumed_signal_sides(conn)
    assert any(ts == "000002.SZ" and st == "filled" for ts, st in rows)
    conn.close()


def test_same_asof_pending_sell_does_not_fill_while_skipping_insert(tmp_path, monkeypatch):
    from scripts.eval.costs import load_costs
    from scripts.eval.shadow_store import load_shadow_book

    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    db = tmp_path / "trend.db"
    bars = tmp_path / "bars.db"
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05")
    _meta(conn, "2024-01-08")
    _meta(conn, "2024-01-09")
    _event(conn, "2024-01-05", "000001.SZ", "ENTER_RIGHT", eid=1)
    _event(conn, "2024-01-08", "000001.SZ", "EXIT_RIGHT", eid=2)
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    _bar_row(bconn, "000001.SZ", "2024-01-08")
    _bar_row(bconn, "000001.SZ", "2024-01-09", open_raw=9.0, down=9.0, up=11.0)
    bconn.commit()
    bconn.close()
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 0
    assert run_asof("2024-01-09", db_path=str(db), bars_path=str(bars)) == 0
    bconn = bars_conn(str(bars))
    bconn.execute(
        "UPDATE bars SET open_raw=10.0, close_raw=10.0, limit_down=9.0 WHERE ts_code=? AND trade_date=?",
        ("000001.SZ", "2024-01-09"),
    )
    bconn.commit()
    bconn.close()
    assert run_asof("2024-01-09", db_path=str(db), bars_path=str(bars)) == 0
    conn = get_conn()
    sells = list(conn.execute("SELECT status, fill_date FROM paper_fill WHERE side='sell'"))
    assert sells == [("unfilled_sell", "2024-01-09")]
    book = load_shadow_book(conn, load_costs())
    assert "000001.SZ" in book.positions
    assert book.pending_sells
    conn.close()
