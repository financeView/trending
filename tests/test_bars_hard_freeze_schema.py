# tests/test_bars_hard_freeze_schema.py
import sqlite3
from scripts.common.bars import BARS_SCHEMA, bars_conn, ensure_bars_columns


def test_ensure_adds_hard_freeze_flag(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE bars (
          ts_code TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          is_suspended INTEGER NOT NULL DEFAULT 0,
          is_st INTEGER NOT NULL DEFAULT 0,
          flag_source TEXT,
          PRIMARY KEY (ts_code, trade_date)
        );
        """
    )
    conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)")}
    assert "hard_freeze_flag" not in cols
    ensure_bars_columns(conn)
    cols2 = {r[1] for r in conn.execute("PRAGMA table_info(bars)")}
    assert "hard_freeze_flag" in cols2
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date) VALUES ('000001.SZ','2024-01-08')"
    )
    conn.commit()
    v = conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code='000001.SZ'"
    ).fetchone()[0]
    assert int(v) == 0
    conn.close()


def test_bars_conn_create_includes_column(tmp_path, monkeypatch):
    db = tmp_path / "new.db"
    monkeypatch.setattr("scripts.common.bars.DEFAULT_BARS_DB", str(db))
    conn = bars_conn(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)")}
    assert "hard_freeze_flag" in cols
    assert "hard_freeze_flag INTEGER" in BARS_SCHEMA.replace("\n", " ") or (
        "hard_freeze_flag" in BARS_SCHEMA
    )
    conn.close()
