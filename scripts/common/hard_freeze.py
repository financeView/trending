"""Spec E: consecutive is_suspended → bars.hard_freeze_flag."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import yaml

from scripts.common.calendar import prev_trade_date

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_METRICS = _ROOT / "config" / "metrics" / "a_share_daily.yaml"


def resolve_metrics_yaml_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("METRICS_PARAMS_YAML")
    if env:
        return Path(env)
    return _DEFAULT_METRICS


@dataclass(frozen=True)
class HardFreezePassConfig:
    min_suspend_days: int
    param_version: str


def load_hard_freeze_pass_config(path: Optional[Path] = None) -> HardFreezePassConfig:
    p = resolve_metrics_yaml_path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    n = int(raw.get("hard_freeze_min_suspend_days") or 20)
    pv = str(raw.get("param_version") or "").strip()
    if not pv:
        raise ValueError("param_version missing in %s" % p)
    return HardFreezePassConfig(min_suspend_days=n, param_version=pv)


def load_hard_freeze_min_suspend_days(path: Optional[Path] = None) -> int:
    return load_hard_freeze_pass_config(path).min_suspend_days


_HARD_FREEZE_PASS_META_DDL = """
CREATE TABLE IF NOT EXISTS hard_freeze_pass_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  hard_freeze_min_suspend_days INTEGER NOT NULL,
  param_version TEXT NOT NULL,
  rewritten_at TEXT NOT NULL,
  rows_touched INTEGER
);
"""


def ensure_hard_freeze_pass_meta(conn) -> None:
    conn.executescript(_HARD_FREEZE_PASS_META_DDL)
    conn.commit()


def write_hard_freeze_pass_meta(
    conn,
    *,
    n: int,
    param_version: str,
    rows_touched: Optional[int] = None,
    rewritten_at: Optional[str] = None,
) -> None:
    ensure_hard_freeze_pass_meta(conn)
    ts = rewritten_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO hard_freeze_pass_meta (
          id, hard_freeze_min_suspend_days, param_version, rewritten_at, rows_touched
        ) VALUES (1,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          hard_freeze_min_suspend_days=excluded.hard_freeze_min_suspend_days,
          param_version=excluded.param_version,
          rewritten_at=excluded.rewritten_at,
          rows_touched=excluded.rows_touched
        """,
        (int(n), str(param_version), ts, rows_touched),
    )
    conn.commit()


def read_hard_freeze_pass_meta(conn) -> Optional[dict]:
    ensure_hard_freeze_pass_meta(conn)
    row = conn.execute(
        """
        SELECT hard_freeze_min_suspend_days, param_version, rewritten_at, rows_touched
        FROM hard_freeze_pass_meta WHERE id=1
        """
    ).fetchone()
    if not row:
        return None
    return {
        "n": int(row[0]),
        "param_version": str(row[1]),
        "rewritten_at": str(row[2]),
        "rows_touched": row[3],
    }


def check_hard_freeze_stamp(
    bars_path: Optional[str] = None,
    yaml_path: Optional[Path] = None,
) -> int:
    """Return 0 if stamp matches yaml; 1 if missing or mismatch. Prints stderr reason."""
    import sys
    from scripts.common.bars import DEFAULT_BARS_DB, bars_conn

    cfg = load_hard_freeze_pass_config(yaml_path)
    path = bars_path or DEFAULT_BARS_DB
    conn = bars_conn(path)
    try:
        meta = read_hard_freeze_pass_meta(conn)
    finally:
        conn.close()
    if meta is None:
        print(
            "[hard_freeze_stamp] missing stamp — run full sync (hard_freeze pass) first",
            file=sys.stderr,
        )
        return 1
    if meta["n"] != cfg.min_suspend_days or meta["param_version"] != cfg.param_version:
        print(
            "[hard_freeze_stamp] mismatch stamp=(n=%s,pv=%s) yaml=(n=%s,pv=%s) "
            "— run full sync to refresh flags+stamp"
            % (meta["n"], meta["param_version"], cfg.min_suspend_days, cfg.param_version),
            file=sys.stderr,
        )
        return 1
    return 0


def apply_hard_freeze_flags(
    conn,
    ts_codes: Sequence[str],
    *,
    n: int,
    commit: bool = True,
) -> int:
    """Rewrite hard_freeze_flag for each ts_code. Returns number of rows touched."""
    written = 0
    for ts in ts_codes:
        rows = conn.execute(
            """
            SELECT trade_date, is_suspended, flag_source
            FROM bars WHERE ts_code=? ORDER BY trade_date ASC
            """,
            (ts,),
        ).fetchall()
        streak = 0
        prev_td = None
        for td_s, sus, src in rows:
            td = date.fromisoformat(str(td_s)[:10])
            if prev_td is not None:
                expect = prev_trade_date(td)
                if expect is None or expect != prev_td:
                    streak = 0
            if not src:
                streak = 0
                flag = 0
            elif int(sus or 0) == 1:
                streak += 1
                flag = 1 if streak >= n else 0
            else:
                streak = 0
                flag = 0
            conn.execute(
                "UPDATE bars SET hard_freeze_flag=? WHERE ts_code=? AND trade_date=?",
                (flag, ts, td_s),
            )
            written += 1
            prev_td = td
    if commit:
        conn.commit()
    return written
