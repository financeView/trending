"""Integration: run_asof hard-fails on vendor_fields + board_calc residue."""
import json
from dataclasses import replace

from scripts.common.bars import LIMIT_SOURCE_BOARD_CALC, bars_conn
from scripts.common.calendar import load_trade_dates_from_list
from scripts.common.db import get_conn, init_schema
from scripts.common.sync_status import write_sync_status
from scripts.eval.costs import load_costs
from scripts.eval.live_shadow_step import run_asof


def _meta(conn, day):
    conn.execute(
        """
        INSERT INTO run_meta (
          trade_date, status, param_version, map_version,
          bar_coverage, computable_coverage, limit_coverage_asof, tradable_count
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (day, "ok", "p-T", "m-T", 1, 1, 1, 5),
    )


def _plant_sot(tmp_path, monkeypatch, session_asof="2024-01-08"):
    p = tmp_path / "sync_status.json"
    monkeypatch.setattr(
        "scripts.common.sync_status.DEFAULT_SYNC_STATUS_PATH", str(p)
    )
    write_sync_status(sync_complete=True, session_asof=session_asof, path=p)


def _fixture(tmp_path, monkeypatch, *, residue=True):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    db = tmp_path / "trend.db"
    bars = tmp_path / "bars.db"
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    _meta(conn, "2024-01-05")
    _meta(conn, "2024-01-08")
    conn.execute(
        """
        INSERT INTO signal_event (id, trade_date, ts_code, event, T, RS, detail)
        VALUES (?,?,?,?,?,?,?)
        """,
        (1, "2024-01-05", "000001.SZ", "ENTER_RIGHT", "hot", 1.0, json.dumps({})),
    )
    conn.commit()
    conn.close()
    bconn = bars_conn(str(bars))
    bconn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, open_raw, close_raw, limit_up, limit_down, limit_source, is_suspended)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "000001.SZ",
            "2024-01-08",
            10.0,
            10.0,
            11.0,
            9.0,
            LIMIT_SOURCE_BOARD_CALC if residue else "em_f51f52",
            0,
        ),
    )
    bconn.commit()
    bconn.close()
    return db, bars


def _costs(limit_rule: str):
    return replace(load_costs(), limit_rule=limit_rule)


def test_vendor_residue_blocks_run_asof(tmp_path, monkeypatch):
    _plant_sot(tmp_path, monkeypatch)
    db, bars = _fixture(tmp_path, monkeypatch, residue=True)
    monkeypatch.setattr(
        "scripts.eval.live_shadow_step.load_costs",
        lambda: _costs("vendor_fields"),
    )
    fills = {"n": 0}
    inserts = {"n": 0}
    monkeypatch.setattr(
        "scripts.eval.live_shadow_step.fill_day",
        lambda *a, **k: fills.__setitem__("n", fills["n"] + 1) or [],
    )
    monkeypatch.setattr(
        "scripts.eval.live_shadow_step.insert_paper_fills",
        lambda *a, **k: inserts.__setitem__("n", inserts["n"] + 1),
    )
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 1
    assert fills["n"] == 0
    assert inserts["n"] == 0


def test_board_calc_rule_allows_residue(tmp_path, monkeypatch):
    _plant_sot(tmp_path, monkeypatch)
    db, bars = _fixture(tmp_path, monkeypatch, residue=True)
    monkeypatch.setattr(
        "scripts.eval.live_shadow_step.load_costs",
        lambda: _costs("board_calc_v1"),
    )
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(bars)) == 0
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0] == 1
    conn.close()


def test_bars_path_homology_dirty_fails_when_default_clean(tmp_path, monkeypatch):
    _plant_sot(tmp_path, monkeypatch)
    db, dirty = _fixture(tmp_path, monkeypatch, residue=True)
    clean = tmp_path / "clean_default.db"
    bars_conn(str(clean)).close()
    monkeypatch.setattr(
        "scripts.eval.live_shadow_step.DEFAULT_BARS_DB", str(clean)
    )
    monkeypatch.setattr(
        "scripts.eval.live_shadow_step.load_costs",
        lambda: _costs("vendor_fields"),
    )
    seen = {"path": None}

    def _guard(path, rule):
        seen["path"] = path
        from scripts.eval.limit_rule_guard import check_limit_rule_bars as real

        return real(path, rule)

    monkeypatch.setattr(
        "scripts.eval.live_shadow_step.check_limit_rule_bars", _guard
    )
    assert run_asof("2024-01-08", db_path=str(db), bars_path=str(dirty)) == 1
    assert seen["path"] == str(dirty)
