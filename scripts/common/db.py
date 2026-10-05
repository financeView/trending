"""trend.db：正式截面 / run_meta / 事件 / paper_fill。"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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
  mapped_size INTEGER,
  mapped_sync_coverage REAL,
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
  stage_score REAL,         -- 可空；结束日必须 SQL NULL，禁止用 0 顶
  stage_score_raw REAL,
  PRIMARY KEY (trade_date, ts_code)
);

CREATE TABLE IF NOT EXISTS daily_l2 (
  trade_date TEXT NOT NULL,
  code TEXT NOT NULL,
  T TEXT,
  S_temp REAL,
  RS REAL,
  right_side INTEGER,
  tag_warm_to_hot INTEGER,
  tag_warm_to_flat INTEGER,
  solar_term TEXT,
  members_tradable INTEGER,
  members_total INTEGER,
  PRIMARY KEY (trade_date, code)
);

CREATE TABLE IF NOT EXISTS daily_l1 (
  trade_date TEXT NOT NULL,
  code TEXT NOT NULL,
  T TEXT,
  S_temp REAL,
  RS REAL,
  right_side INTEGER,
  tag_warm_to_hot INTEGER,
  tag_warm_to_flat INTEGER,
  solar_term TEXT,
  members_tradable INTEGER,
  members_total INTEGER,
  PRIMARY KEY (trade_date, code)
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

CREATE UNIQUE INDEX IF NOT EXISTS paper_fill_event_side_date
  ON paper_fill(signal_event_id, side, fill_date)
  WHERE signal_event_id IS NOT NULL AND IFNULL(track, 'L') = 'L';

CREATE TABLE IF NOT EXISTS shadow_book_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  payload TEXT NOT NULL
);
"""

RUN_META_ALTER_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("mapped_size", "INTEGER"),
    ("mapped_sync_coverage", "REAL"),
)

DAILY_STOCK_ALTER_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("hard_frozen", "INTEGER"),
    ("close_qfq", "REAL"),
    ("float_mv", "REAL"),
    ("stage_score", "REAL"),
    ("stage_score_raw", "REAL"),
    ("tag_warm_to_hot", "INTEGER"),
    ("tag_warm_to_flat", "INTEGER"),
    ("solar_term", "TEXT"),
    ("S_temp", "REAL"),
    ("RS", "REAL"),
    ("right_side", "INTEGER"),
    ("amount", "REAL"),
)

DAILY_BASKET_ALTER_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("T", "TEXT"),
    ("S_temp", "REAL"),
    ("RS", "REAL"),
    ("right_side", "INTEGER"),
    ("tag_warm_to_hot", "INTEGER"),
    ("tag_warm_to_flat", "INTEGER"),
    ("solar_term", "TEXT"),
    ("members_tradable", "INTEGER"),
    ("members_total", "INTEGER"),
)

DAILY_STOCK_COLS = (
    "trade_date",
    "ts_code",
    "sw_l2_code",
    "l1_id",
    "T",
    "S_temp",
    "RS",
    "universe_id",
    "right_side",
    "right_side_days_natural",
    "right_side_days_trading",
    "tag_warm_to_hot",
    "tag_warm_to_flat",
    "solar_term",
    "hard_frozen",
    "amount",
    "close_qfq",
    "float_mv",
    "stage_score",
    "stage_score_raw",
)

DAILY_BASKET_COLS = (
    "trade_date",
    "code",
    "T",
    "S_temp",
    "RS",
    "right_side",
    "tag_warm_to_hot",
    "tag_warm_to_flat",
    "solar_term",
    "members_tradable",
    "members_total",
)

_INT_BOOL_COLS = frozenset(
    {
        "right_side",
        "right_side_days_natural",
        "right_side_days_trading",
        "tag_warm_to_hot",
        "tag_warm_to_flat",
        "hard_frozen",
        "members_tradable",
        "members_total",
    }
)

SIGNAL_EVENT_COLS = (
    "trade_date",
    "ts_code",
    "l1_id",
    "sw_l2_code",
    "event",
    "T",
    "RS",
    "detail",
    "superseded_by",
)

PAPER_FILL_COLS = (
    "fill_id",
    "track",
    "rule_id",
    "cost_version",
    "param_version",
    "map_version",
    "signal_event_id",
    "signal_date",
    "intent_date",
    "fill_date",
    "ts_code",
    "side",
    "exit_kind",
    "qty",
    "px",
    "costs",
    "status",
    "reject_reason",
    "run_id",
)


def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or os.environ.get("TREND_DB") or DEFAULT_DB
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    return {r[1] for r in rows}


def _ensure_columns(
    conn: sqlite3.Connection, table: str, columns: Sequence[Tuple[str, str]]
) -> None:
    existing = _table_columns(conn, table)
    if not existing:
        return
    for name, decl in columns:
        if name in existing:
            continue
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))
        existing.add(name)


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Idempotent: create missing tables, ALTER-add missing daily_* columns."""
    conn.executescript(SCHEMA)
    _ensure_columns(conn, "run_meta", RUN_META_ALTER_COLUMNS)
    _ensure_columns(conn, "daily_stock", DAILY_STOCK_ALTER_COLUMNS)
    _ensure_columns(conn, "daily_l2", DAILY_BASKET_ALTER_COLUMNS)
    _ensure_columns(conn, "daily_l1", DAILY_BASKET_ALTER_COLUMNS)
    conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    migrate_schema(conn)


def _as_sql_int(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    return value


def _prepare_row(row: Dict[str, Any], allowed: Sequence[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if k not in allowed:
            continue
        if k in _INT_BOOL_COLS:
            v = _as_sql_int(v)
        out[k] = v
    return out


def _upsert_conflict(
    conn: sqlite3.Connection,
    table: str,
    pk: Sequence[str],
    allowed: Sequence[str],
    rows: List[Dict[str, Any]],
    commit: bool = True,
) -> int:
    if not rows:
        return 0
    n = 0
    for raw in rows:
        row = _prepare_row(raw, allowed)
        missing = [c for c in pk if c not in row or row[c] is None]
        if missing:
            raise ValueError("%s missing PK %s in %r" % (table, missing, raw))
        cols = [c for c in allowed if c in row]
        placeholders = ",".join(["?"] * len(cols))
        collist = ",".join(cols)
        non_pk = [c for c in cols if c not in pk]
        if non_pk:
            updates = ",".join("%s=excluded.%s" % (c, c) for c in non_pk)
            conflict = "ON CONFLICT(%s) DO UPDATE SET %s" % (",".join(pk), updates)
        else:
            conflict = "ON CONFLICT(%s) DO NOTHING" % ",".join(pk)
        sql = "INSERT INTO %s (%s) VALUES (%s) %s" % (table, collist, placeholders, conflict)
        conn.execute(sql, [row[c] for c in cols])
        n += 1
    if commit:
        conn.commit()
    return n


def upsert_daily_stock(
    conn: sqlite3.Connection, rows: List[Dict[str, Any]], commit: bool = True
) -> int:
    return _upsert_conflict(
        conn, "daily_stock", ("trade_date", "ts_code"), DAILY_STOCK_COLS, rows, commit
    )


def upsert_daily_l2(
    conn: sqlite3.Connection, rows: List[Dict[str, Any]], commit: bool = True
) -> int:
    return _upsert_conflict(
        conn, "daily_l2", ("trade_date", "code"), DAILY_BASKET_COLS, rows, commit
    )


def upsert_daily_l1(
    conn: sqlite3.Connection, rows: List[Dict[str, Any]], commit: bool = True
) -> int:
    return _upsert_conflict(
        conn, "daily_l1", ("trade_date", "code"), DAILY_BASKET_COLS, rows, commit
    )


def canonical_detail(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, (dict, list)):
        return json.dumps(detail, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if isinstance(detail, str):
        s = detail.strip()
        if not s:
            return ""
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return s
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return s
    return json.dumps(detail, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _norm_t(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _rs_equal(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)


def _event_identity(ev: Dict[str, Any]) -> Tuple[str, str, str]:
    trade_date = str(ev["trade_date"])
    event = str(ev["event"])
    code = ev.get("ts_code") or ev.get("code") or ""
    return trade_date, str(code), event


def _payload_tuple(t: Any, rs: Any, detail: Any) -> Tuple[Optional[str], Any, str]:
    return (_norm_t(t), None if rs is None else float(rs), canonical_detail(detail))


def _payloads_equal(
    a: Tuple[Optional[str], Any, str], b: Tuple[Optional[str], Any, str]
) -> bool:
    return a[0] == b[0] and _rs_equal(a[1], b[1]) and a[2] == b[2]


def append_signal_events(
    conn: sqlite3.Connection, events: Iterable[Dict[str, Any]], commit: bool = True
) -> List[int]:
    """Insert events; supersede active row only when T/RS/detail payload differs."""
    inserted: List[int] = []
    for ev in events:
        trade_date, ts_code, event = _event_identity(ev)
        new_payload = _payload_tuple(ev.get("T"), ev.get("RS"), ev.get("detail"))
        active = conn.execute(
            """
            SELECT id, T, RS, detail FROM signal_event
            WHERE trade_date=? AND ts_code=? AND event=? AND superseded_by IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (trade_date, ts_code, event),
        ).fetchone()
        if active is not None:
            old_payload = _payload_tuple(active[1], active[2], active[3])
            if _payloads_equal(old_payload, new_payload):
                continue
        row = {
            "trade_date": trade_date,
            "ts_code": ts_code,
            "l1_id": ev.get("l1_id"),
            "sw_l2_code": ev.get("sw_l2_code"),
            "event": event,
            "T": new_payload[0],
            "RS": None if ev.get("RS") is None else float(ev["RS"]),
            "detail": new_payload[2] if new_payload[2] else None,
            "superseded_by": None,
        }
        cols = [c for c in SIGNAL_EVENT_COLS if c in row]
        sql = "INSERT INTO signal_event (%s) VALUES (%s)" % (
            ",".join(cols),
            ",".join(["?"] * len(cols)),
        )
        cur = conn.execute(sql, [row[c] for c in cols])
        new_id = int(cur.lastrowid)
        if active is not None:
            conn.execute(
                "UPDATE signal_event SET superseded_by=? WHERE id=?",
                (new_id, active[0]),
            )
        inserted.append(new_id)
    if commit:
        conn.commit()
    return inserted


def insert_paper_fills(
    conn: sqlite3.Connection, rows: Iterable[Dict[str, Any]], commit: bool = True
) -> int:
    """Append-only. Duplicate fill_id or (signal_event_id, side, fill_date) is skipped."""
    n = 0
    for row in rows:
        fid = row.get("fill_id")
        if not fid:
            raise ValueError("paper_fill requires fill_id")
        existing = conn.execute(
            "SELECT fill_id FROM paper_fill WHERE fill_id=?",
            (fid,),
        ).fetchone()
        if existing is not None:
            continue
        sid = row.get("signal_event_id")
        side = row.get("side")
        fill_date = row.get("fill_date")
        track = row.get("track") or "L"
        if track == "L" and sid is not None and side and fill_date:
            clash = conn.execute(
                """
                SELECT fill_id FROM paper_fill
                WHERE signal_event_id=? AND side=? AND fill_date=?
                  AND IFNULL(track, 'L') = 'L'
                """,
                (int(sid), str(side), str(fill_date)),
            ).fetchone()
            if clash is not None:
                continue
        cols = [c for c in PAPER_FILL_COLS if c in row]
        sql = "INSERT INTO paper_fill (%s) VALUES (%s)" % (
            ",".join(cols),
            ",".join(["?"] * len(cols)),
        )
        conn.execute(sql, [row.get(c) for c in cols])
        n += 1
    if commit:
        conn.commit()
    return n


def consumed_signal_sides(conn: sqlite3.Connection) -> set:
    """Pairs (signal_event_id, side) that already have a terminal paper_fill row."""
    rows = conn.execute(
        """
        SELECT signal_event_id, side FROM paper_fill
        WHERE signal_event_id IS NOT NULL AND IFNULL(track, 'L') = 'L'
        """
    ).fetchall()
    return {(int(a), str(b)) for a, b in rows if a is not None}


def paper_fill_keys_on_date(conn: sqlite3.Connection, fill_date: str) -> set:
    """(signal_event_id, side, fill_date) already written for L on this session."""
    rows = conn.execute(
        """
        SELECT signal_event_id, side FROM paper_fill
        WHERE fill_date=? AND signal_event_id IS NOT NULL AND IFNULL(track, 'L') = 'L'
        """,
        (fill_date,),
    ).fetchall()
    return {(int(a), str(b), fill_date) for a, b in rows if a is not None}


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
