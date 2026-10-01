"""trend.db：正式截面 / run_meta / 事件 / paper_fill。"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "trend.db"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS run_meta (
  trade_date TEXT PRIMARY KEY,
  param_version TEXT,
  map_version TEXT,
  member_set TEXT,
  universe_size INTEGER,
  unmapped_count INTEGER,
  tradable_count INTEGER,
  bar_coverage REAL,
  computable_coverage REAL,
  limit_coverage_asof REAL,
  open_raw_coverage_asof REAL,
  ok_predicate_version TEXT,
  git_sha TEXT,
  started_at TEXT,
  finished_at TEXT,
  status TEXT,
  warn TEXT
);

CREATE TABLE IF NOT EXISTS daily_stock (
  trade_date TEXT NOT NULL,
  ts_code TEXT NOT NULL,
  sw_l2_code TEXT,
  l1_id TEXT,
  T TEXT,
  S_temp REAL,
  RS REAL,
  universe_id TEXT,
  right_side INTEGER,
  right_side_days_natural INTEGER,
  right_side_days_trading INTEGER,
  tag_warm_to_hot INTEGER,
  tag_warm_to_flat INTEGER,
  solar_term TEXT,
  hard_frozen INTEGER,      -- P0 占位；P0.5+ 由 metrics 写入
  amount REAL,
  close_qfq REAL,           -- 前复权收盘；盯市用 bars.close_raw
  float_mv REAL,
  PRIMARY KEY (trade_date, ts_code)
);

CREATE TABLE IF NOT EXISTS signal_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date TEXT,
  ts_code TEXT,
  l1_id TEXT,
  sw_l2_code TEXT,
  event TEXT,
  T TEXT,
  RS REAL,
  detail TEXT,
  superseded_by INTEGER
);

CREATE TABLE IF NOT EXISTS paper_fill (
  fill_id TEXT PRIMARY KEY,
  track TEXT,
  rule_id TEXT,
  cost_version TEXT,
  param_version TEXT,
  map_version TEXT,
  signal_event_id INTEGER,
  signal_date TEXT,
  intent_date TEXT,
  fill_date TEXT,
  ts_code TEXT,
  side TEXT,
  exit_kind TEXT,
  qty REAL,
  px REAL,
  costs REAL,
  status TEXT,
  reject_reason TEXT,
  run_id TEXT
);
"""


def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or os.environ.get("TREND_DB") or DEFAULT_DB
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_rows(conn, table: str, rows: List[Dict[str, Any]], commit: bool = True) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ",".join(["?"] * len(cols))
    collist = ",".join(cols)
    sql = "INSERT OR REPLACE INTO %s (%s) VALUES (%s)" % (table, collist, placeholders)
    conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    if commit:
        conn.commit()
    return len(rows)


def last_ok_trade_date(conn: sqlite3.Connection) -> Optional[str]:
    """连续 ok 前缀的末交易日（market-data §7.3）。

    不得用「任意最大 ok 日」——中间若有 partial/fail，返回缺口前最后一个 ok。
    """
    rows = conn.execute(
        "SELECT trade_date, status FROM run_meta ORDER BY trade_date ASC"
    ).fetchall()
    last: Optional[str] = None
    for trade_date, status in rows:
        if status == "ok":
            last = trade_date
        else:
            break
    return last


def first_unfinished_trade_date(conn: sqlite3.Connection) -> Optional[str]:
    """首个非 ok 行（partial/fail/…）；无则 None（整表连续 ok 或空表）。"""
    row = conn.execute(
        """
        SELECT trade_date FROM run_meta
        WHERE status IS NULL OR status != 'ok'
        ORDER BY trade_date ASC
        LIMIT 1
        """
    ).fetchone()
    return row[0] if row else None


def write_heartbeat(payload: Dict[str, Any], path: Optional[str] = None) -> None:
    path = path or os.path.join(os.path.dirname(DEFAULT_DB), "heartbeat.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
            data = {k: v for k, v in old.items() if isinstance(v, dict)}
        except Exception:
            data = {}
    payload = dict(payload)
    job = payload.pop("job", "daily_run")
    key = "last_error" if payload.get("status") == "error" else "last_success"
    payload[key] = dt.datetime.now().isoformat(timespec="seconds")
    data[job] = payload
    data["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
