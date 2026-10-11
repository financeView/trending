"""live_shadow fill gated by sync_status SoT (incomplete-asof Spec)."""
import json

from scripts.common.bars import bars_conn
from scripts.common.calendar import load_trade_dates_from_list
from scripts.common.db import get_conn, init_schema
from scripts.common.sync_status import write_sync_status
from scripts.eval.live_shadow_step import run_asof


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


def _bar_row(conn, ts, day):
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, open_raw, close_raw, limit_up, limit_down, is_suspended)
        VALUES (?,?,?,?,?,?,?)
        """,
        (ts, day, 10.0, 10.0, 11.0, 9.0, 0),
    )


def _plant_sot(tmp_path, monkeypatch, *, session_asof: str, sync_complete: bool = True):
    p = tmp_path / "sync_status.json"
    monkeypatch.setattr(
        "scripts.common.sync_status.DEFAULT_SYNC_STATUS_PATH", str(p)
    )
    write_sync_status(
        sync_complete=sync_complete,
        session_asof=session_asof,
        path=p,
    )
    return p


def _would_fill_fixture(tmp_path, monkeypatch, *, fill_asof="2024-01-08"):
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
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    _bar_row(bconn, "000001.SZ", fill_asof)
    if fill_asof != "2024-01-08":
        _bar_row(bconn, "000001.SZ", "2024-01-08")
    bconn.commit()
    bconn.close()
    return db, bars


def test_missing_sot_would_fill_returns_1(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.common.sync_status.DEFAULT_SYNC_STATUS_PATH",
        str(tmp_path / "missing_sync_status.json"),
    )
    db, bars = _would_fill_fixture(tmp_path, monkeypatch)
    inserts = {"n": 0}

    def _ins(*a, **k):
        inserts["n"] += 1

    monkeypatch.setattr("scripts.eval.live_shadow_step.insert_paper_fills", _ins)
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 1
    assert inserts["n"] == 0
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0] == 0
    conn.close()


def test_calendar_skip_without_sot_returns_0(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.common.sync_status.DEFAULT_SYNC_STATUS_PATH",
        str(tmp_path / "missing_sync_status.json"),
    )
    load_trade_dates_from_list(["2024-01-08"])
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-09")
    conn.commit()
    conn.close()
    assert run_asof("2024-01-09", db_path=str(tmp_path / "trend.db")) == 0


def test_missing_bars_without_sot_returns_0(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.common.sync_status.DEFAULT_SYNC_STATUS_PATH",
        str(tmp_path / "missing_sync_status.json"),
    )
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


def test_tip_d2_authorizes_fill_d1(tmp_path, monkeypatch):
    _plant_sot(tmp_path, monkeypatch, session_asof="2024-01-09")
    db, bars = _would_fill_fixture(tmp_path, monkeypatch, fill_asof="2024-01-08")
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 0
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0] == 1
    conn.close()


def test_stale_tip_d1_rejects_fill_d2(tmp_path, monkeypatch):
    _plant_sot(tmp_path, monkeypatch, session_asof="2024-01-08")
    db, bars = _would_fill_fixture(tmp_path, monkeypatch, fill_asof="2024-01-09")
    # also need confirm meta chain for 2024-01-09 fill (confirm=2024-01-08 ok)
    inserts = {"n": 0}
    monkeypatch.setattr(
        "scripts.eval.live_shadow_step.insert_paper_fills",
        lambda *a, **k: inserts.__setitem__("n", inserts["n"] + 1),
    )
    assert run_asof("2024-01-09", db_path=str(db), bars_path=str(bars)) == 1
    assert inserts["n"] == 0


def test_incomplete_sot_rejects_fill(tmp_path, monkeypatch):
    _plant_sot(tmp_path, monkeypatch, session_asof="2024-01-08", sync_complete=False)
    db, bars = _would_fill_fixture(tmp_path, monkeypatch)
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 1


def test_from_heartbeat_keeps_earlier_gate_fail(tmp_path, monkeypatch):
    """Later soft-skip (0) must not mask an earlier sync_authority fail (1)."""
    from scripts.eval.live_shadow_step import main

    monkeypatch.setattr(
        "scripts.common.sync_status.DEFAULT_SYNC_STATUS_PATH",
        str(tmp_path / "missing_sync_status.json"),
    )
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    db = tmp_path / "trend.db"
    bars = tmp_path / "bars.db"
    hb = tmp_path / "heartbeat.json"
    hb.write_text(
        json.dumps(
            {
                "status": "ok",
                "days": ["2024-01-08", "2024-01-09"],
                "asof": "2024-01-09",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    for day in ("2024-01-05", "2024-01-08", "2024-01-09"):
        _meta(conn, day)
    _event(conn, "2024-01-05", "000001.SZ", "ENTER_RIGHT", eid=1)
    # D2 has a pending name but no bars → missing_bars soft-skip 0
    _event(conn, "2024-01-08", "000002.SZ", "ENTER_RIGHT", eid=2)
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    _bar_row(bconn, "000001.SZ", "2024-01-08")
    bconn.commit()
    bconn.close()

    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 1
    assert run_asof("2024-01-09", db_path=str(db), bars_path=str(bars)) == 0
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
    assert rc == 1
