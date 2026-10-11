"""Hard-fail when vendor_fields costs meet residual board_calc_v1 limits."""
from __future__ import annotations

import os
import sqlite3
import sys

from scripts.common.bars import LIMIT_SOURCE_BOARD_CALC

_FAIL_MSG = (
    "[limit_rule_guard] vendor_fields but bars still have board_calc_v1 limits — "
    "clear those rows (whole DB) or set limit_rule=board_calc_v1 (+ bump cost_version)"
)


def check_limit_rule_bars(bars_path: str, limit_rule: str) -> int:
    """Return 0 if ok; 1 if vendor_fields + bilateral board_calc residue (or unreadable)."""
    rule = (limit_rule or "vendor_fields").strip() or "vendor_fields"
    if rule != "vendor_fields":
        return 0
    if not bars_path or not os.path.isfile(bars_path):
        print(_FAIL_MSG, file=sys.stderr)
        return 1
    try:
        conn = sqlite3.connect(f"file:{bars_path}?mode=ro", uri=True)
    except sqlite3.Error:
        print(_FAIL_MSG, file=sys.stderr)
        return 1
    try:
        row = conn.execute(
            """
            SELECT 1 FROM bars
            WHERE limit_source = ?
              AND limit_up IS NOT NULL
              AND limit_down IS NOT NULL
            LIMIT 1
            """,
            (LIMIT_SOURCE_BOARD_CALC,),
        ).fetchone()
    except sqlite3.Error:
        print(_FAIL_MSG, file=sys.stderr)
        return 1
    finally:
        conn.close()
    if row is not None:
        print(_FAIL_MSG, file=sys.stderr)
        return 1
    return 0
