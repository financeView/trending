"""Spec E: consecutive is_suspended → bars.hard_freeze_flag."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional, Sequence

import yaml

from scripts.common.calendar import prev_trade_date

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_METRICS = _ROOT / "config" / "metrics" / "a_share_daily.yaml"


def load_hard_freeze_min_suspend_days(path: Optional[Path] = None) -> int:
    p = Path(path) if path else _DEFAULT_METRICS
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return int(raw.get("hard_freeze_min_suspend_days") or 20)


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
