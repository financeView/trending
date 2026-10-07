"""分类宇宙与 members_tradable（metrics §3.2 / market-data-contract §7.2）。"""
from __future__ import annotations

import os
import sqlite3
from datetime import date
from typing import Iterable, List, Optional, Sequence, Set

import yaml

from scripts.common.ts_code import to_ts_code

_L2_TO_L1 = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "config",
    "taxonomy",
    "sw_l2_to_l1.yaml",
)
_STOCK_SW_L2 = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "config",
    "taxonomy",
    "stock_sw_l2.yaml",
)


def _yaml_mapping(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("yaml must be a mapping: %s" % path)
    return data


def load_l2_to_l1(path: Optional[str] = None) -> List[dict]:
    data = _yaml_mapping(path or _L2_TO_L1)
    rows = data.get("l2") or []
    out = []
    seen = set()
    for row in rows:
        code = str(row["code"])
        if code in seen:
            raise ValueError("duplicate sw_l2_code %s" % code)
        seen.add(code)
        out.append(
            {
                "code": code,
                "name_zh": row.get("name_zh"),
                "l1_id": row["l1_id"],
                "sort_order": row.get("sort_order"),
            }
        )
    return out


def section4_codes(path: Optional[str] = None) -> Set[str]:
    return {r["code"] for r in load_l2_to_l1(path)}


_STOCK_CACHE = None


def load_stock_sw_l2(path: Optional[str] = None) -> List[dict]:
    global _STOCK_CACHE
    p = path or _STOCK_SW_L2
    if path is None and _STOCK_CACHE is not None:
        return _STOCK_CACHE
    data = _yaml_mapping(p)
    members = data.get("members") or []
    out = []
    for m in members:
        if isinstance(m, str):
            out.append({"ts_code": to_ts_code(m), "sw_l2_code": None, "name_zh": None})
            continue
        ts = to_ts_code(m["ts_code"])
        raw = m.get("sw_l2_code")
        code = None if raw in (None, "") else str(raw)
        name = m.get("name_zh")
        name_zh = None if name in (None, "") else str(name)
        out.append({"ts_code": ts, "sw_l2_code": code, "name_zh": name_zh})
    if path is None:
        _STOCK_CACHE = out
    return out


def _ts_sh_sz(ts: str) -> bool:
    return len(ts) == 9 and ts[:6].isdigit() and ts.endswith((".SH", ".SZ"))


def _codes_from_stock_rows(rows: List[dict]) -> List[str]:
    allowed = section4_codes()
    seen: List[str] = []
    have = set()
    for row in rows:
        ts, code = row["ts_code"], row["sw_l2_code"]
        if not _ts_sh_sz(ts):
            continue
        if not code or code not in allowed or str(code).startswith("801"):
            continue
        if ts not in have:
            have.add(ts)
            seen.append(ts)
    return seen


def load_universe_codes(path: Optional[str] = None, stock_path: Optional[str] = None) -> List[str]:
    """Mapped SH/SZ universe. Stub member-list YAML only via path / UNIVERSE_YAML."""
    if stock_path is not None:
        return _codes_from_stock_rows(load_stock_sw_l2(stock_path))
    override = path or os.environ.get("UNIVERSE_YAML")
    if override:
        data = _yaml_mapping(override)
        members = data.get("members") or []
        if members and isinstance(members[0], dict):
            return _codes_from_stock_rows(load_stock_sw_l2(override))
        return [to_ts_code(c) for c in members]
    return _codes_from_stock_rows(load_stock_sw_l2())


def load_map_version(path: Optional[str] = None) -> str:
    override = path or os.environ.get("UNIVERSE_YAML")
    if override:
        raw = _yaml_mapping(override).get("map_version")
        if raw is None or str(raw).strip() == "":
            raise ValueError("universe yaml missing map_version")
        return str(raw)
    raw = _yaml_mapping(_L2_TO_L1).get("map_version")
    if raw is None or str(raw).strip() == "":
        raise ValueError("sw_l2_to_l1 yaml missing map_version")
    return str(raw)


def load_quarantine_codes(path: Optional[str] = None) -> Set[str]:
    override = path or os.environ.get("UNIVERSE_YAML")
    if override:
        data = _yaml_mapping(override)
        members = data.get("members") or []
        if not members or isinstance(members[0], str):
            return {to_ts_code(c) for c in (data.get("quarantine") or [])}
    allowed = section4_codes()
    out: Set[str] = set()
    stock = override if override else None
    for row in load_stock_sw_l2(stock):
        ts, code = row["ts_code"], row["sw_l2_code"]
        if not _ts_sh_sz(ts):
            continue
        if not code or code not in allowed:
            out.add(ts)
    return out


def l2_members_map(stock_path: Optional[str] = None) -> dict:
    mapping: dict = {}
    for row in load_stock_sw_l2(stock_path):
        code = row["sw_l2_code"]
        ts = row["ts_code"]
        if not code or not _ts_sh_sz(ts):
            continue
        mapping.setdefault(code, []).append(ts)
    return mapping


def l1_to_l2_map() -> dict:
    mapping: dict = {}
    for row in load_l2_to_l1():
        mapping.setdefault(row["l1_id"], []).append(row["code"])
    return mapping


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
