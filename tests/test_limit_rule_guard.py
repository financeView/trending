"""Unit tests for check_limit_rule_bars (limit_rule rollback Spec)."""
import os

from scripts.common.bars import LIMIT_SOURCE_BOARD_CALC, LIMIT_SOURCE_EM, bars_conn
from scripts.eval.limit_rule_guard import check_limit_rule_bars


def _bilateral(conn, ts="000001.SZ", day="2024-01-08", source=LIMIT_SOURCE_BOARD_CALC):
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, open_raw, close_raw, limit_up, limit_down, limit_source)
        VALUES (?,?,?,?,?,?,?)
        """,
        (ts, day, 10.0, 10.0, 11.0, 9.0, source),
    )


def test_vendor_with_board_calc_residue_fails(tmp_path):
    db = tmp_path / "dirty.db"
    conn = bars_conn(str(db))
    _bilateral(conn)
    conn.commit()
    conn.close()
    assert check_limit_rule_bars(str(db), "vendor_fields") == 1


def test_vendor_empty_or_vendor_sources_ok(tmp_path):
    empty = tmp_path / "empty.db"
    bars_conn(str(empty)).close()
    assert check_limit_rule_bars(str(empty), "vendor_fields") == 0

    clean = tmp_path / "vendor.db"
    conn = bars_conn(str(clean))
    _bilateral(conn, source=LIMIT_SOURCE_EM)
    conn.commit()
    conn.close()
    assert check_limit_rule_bars(str(clean), "vendor_fields") == 0


def test_board_calc_rule_ignores_residue(tmp_path):
    db = tmp_path / "bc.db"
    conn = bars_conn(str(db))
    _bilateral(conn)
    conn.commit()
    conn.close()
    assert check_limit_rule_bars(str(db), "board_calc_v1") == 0


def test_one_sided_board_calc_ignored(tmp_path):
    db = tmp_path / "oneside.db"
    conn = bars_conn(str(db))
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, open_raw, close_raw, limit_up, limit_down, limit_source)
        VALUES (?,?,?,?,?,?,?)
        """,
        ("000001.SZ", "2024-01-08", 10.0, 10.0, 11.0, None, LIMIT_SOURCE_BOARD_CALC),
    )
    conn.commit()
    conn.close()
    assert check_limit_rule_bars(str(db), "vendor_fields") == 0


def test_missing_bars_path_fails():
    assert check_limit_rule_bars("/nonexistent/bars.db", "vendor_fields") == 1


def test_homology_dirty_vs_clean_paths(tmp_path):
    dirty = tmp_path / "a.db"
    clean = tmp_path / "b.db"
    c1 = bars_conn(str(dirty))
    _bilateral(c1)
    c1.commit()
    c1.close()
    bars_conn(str(clean)).close()
    assert check_limit_rule_bars(str(dirty), "vendor_fields") == 1
    assert check_limit_rule_bars(str(clean), "vendor_fields") == 0


def test_fail_stderr_actionable(tmp_path, capsys):
    db = tmp_path / "dirty.db"
    conn = bars_conn(str(db))
    _bilateral(conn)
    conn.commit()
    conn.close()
    assert check_limit_rule_bars(str(db), "vendor_fields") == 1
    err = capsys.readouterr().err
    assert "board_calc_v1" in err
    assert "clear" in err.lower() or "clear those rows" in err
    assert "cost_version" in err


def test_trending_env_does_not_bypass(tmp_path, monkeypatch):
    monkeypatch.setenv("TRENDING_ALLOW_INCOMPLETE_FILL", "1")
    monkeypatch.setenv("TRENDING_SKIP_LIMIT_RULE", "1")
    db = tmp_path / "dirty.db"
    conn = bars_conn(str(db))
    _bilateral(conn)
    conn.commit()
    conn.close()
    assert check_limit_rule_bars(str(db), "vendor_fields") == 1
    assert os.environ.get("TRENDING_ALLOW_INCOMPLETE_FILL") == "1"
