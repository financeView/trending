"""分类宇宙与 members_tradable（metrics §3.2 / market-data-contract §7.2）。"""
from __future__ import annotations

import os
import sqlite3
from datetime import date
from typing import Iterable, List, Optional, Sequence, Set

import yaml

from scripts.common.ts_code import to_ts_code

_DEFAULT_UNIVERSE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "config",
    "taxonomy",
    "universe_stub.yaml",
)


def load_universe_codes(path: Optional[str] = None) -> List[str]:
    """加载分类宇宙 ts_code 列表（stub YAML，直至完整 SW 映射）。"""
    p = path or os.environ.get("UNIVERSE_YAML") or _DEFAULT_UNIVERSE
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    members = data.get("members") or []
    return [to_ts_code(c) for c in members]


def load_quarantine_codes(path: Optional[str] = None) -> Set[str]:
    p = path or os.environ.get("UNIVERSE_YAML") or _DEFAULT_UNIVERSE
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {to_ts_code(c) for c in (data.get("quarantine") or [])}


def members_tradable(
    conn: sqlite3.Connection,
    trade_date: date,
    *,
    universe: Optional[Sequence[str]] = None,
    quarantine: Optional[Iterable[str]] = None,
) -> List[str]:
    """U = 分类宇宙 ∧ 非 quarantine ∧ 非 ST ∧ 非停牌。

    须有当日 bar 且 flag_source 非空（已同步 BaoStock 等），才能确认非 ST/停牌。
    无 bar / 无 flags → 不进入 U（不等于把缺 bar 当停牌）。
    """
    uni = [to_ts_code(c) for c in (universe if universe is not None else load_universe_codes())]
    qua = {to_ts_code(c) for c in (quarantine if quarantine is not None else load_quarantine_codes())}
    td = trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
    out: List[str] = []
    for ts in uni:
        if ts in qua:
            continue
        row = conn.execute(
            """
            SELECT is_st, is_suspended, flag_source
            FROM bars WHERE ts_code=? AND trade_date=?
            """,
            (ts, td),
        ).fetchone()
        if row is None:
            continue
        is_st, is_suspended, flag_source = row
        if not flag_source:
            continue
        if int(is_st or 0) == 1 or int(is_suspended or 0) == 1:
            continue
        out.append(ts)
    return out
