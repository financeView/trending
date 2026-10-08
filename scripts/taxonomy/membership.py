"""Membership diff, map_version bump, and refresh guard helpers."""
from __future__ import annotations

import re
from typing import Optional, TypedDict

import yaml

_MAP_VERSION_RE = re.compile(r"^map_version:\s*.*$", re.MULTILINE)
_BUMP_RE = re.compile(r"^sw2021-v(\d+)$")


class Member(TypedDict):
    ts_code: str
    sw_l2_code: Optional[str]
    name_zh: Optional[str]


def _norm_sw_l2(raw: object) -> Optional[str]:
    if raw in (None, ""):
        return None
    return str(raw)


def _parse_member(raw: object) -> Member:
    if isinstance(raw, str):
        return {"ts_code": raw.strip(), "sw_l2_code": None, "name_zh": None}
    if not isinstance(raw, dict):
        raise ValueError("invalid member entry")
    ts = str(raw.get("ts_code") or "").strip()
    return {
        "ts_code": ts,
        "sw_l2_code": _norm_sw_l2(raw.get("sw_l2_code")),
        "name_zh": _norm_sw_l2(raw.get("name_zh")),
    }


def load_members_from_yaml(path: str) -> tuple[str, list[Member]]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    version = str(data.get("map_version") or "")
    members = [_parse_member(m) for m in data.get("members") or []]
    members.sort(key=lambda m: m["ts_code"])
    return version, members


def semantic_equal(a: list[Member], b: list[Member]) -> bool:
    if len(a) != len(b):
        return False
    sa = sorted(a, key=lambda m: m["ts_code"])
    sb = sorted(b, key=lambda m: m["ts_code"])
    for ma, mb in zip(sa, sb):
        if ma["ts_code"] != mb["ts_code"]:
            return False
        if _norm_sw_l2(ma.get("sw_l2_code")) != _norm_sw_l2(mb.get("sw_l2_code")):
            return False
        if _norm_sw_l2(ma.get("name_zh")) != _norm_sw_l2(mb.get("name_zh")):
            return False
    return True


def membership_delta(head: list[Member], cand: list[Member]) -> tuple[int, int, int]:
    by_head = {m["ts_code"]: m for m in head}
    by_cand = {m["ts_code"]: m for m in cand}
    head_ts = set(by_head)
    cand_ts = set(by_cand)
    adds = len(cand_ts - head_ts)
    deletes = len(head_ts - cand_ts)
    changes = 0
    for ts in head_ts & cand_ts:
        h = _norm_sw_l2(by_head[ts].get("sw_l2_code"))
        c = _norm_sw_l2(by_cand[ts].get("sw_l2_code"))
        if h != c:
            changes += 1
    return adds, deletes, changes


def guard_ok(
    head_mapped_n: int,
    cand_mapped_n: int,
    adds: int,
    deletes: int,
    changes: int,
    *,
    min_frac: float = 0.8,
    max_delta: int = 80,
) -> bool:
    if head_mapped_n <= 0:
        return cand_mapped_n >= 0 and adds + deletes + changes <= max_delta
    if cand_mapped_n < min_frac * head_mapped_n:
        return False
    if adds + deletes + changes > max_delta:
        return False
    return True


def bump_map_version(current: str) -> str:
    m = _BUMP_RE.match((current or "").strip())
    if not m:
        raise ValueError("invalid map_version: %r" % current)
    n = int(m.group(1))
    return "sw2021-v%d" % (n + 1)


def patch_map_version_header(path: str, new_version: str) -> None:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    replacement = "map_version: %s" % new_version
    new_text, n = _MAP_VERSION_RE.subn(replacement, text, count=1)
    if n == 0:
        raise ValueError("no map_version line in %s" % path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)


def mapped_count(members: list[Member], allowed: set[str]) -> int:
    n = 0
    for m in members:
        code = _norm_sw_l2(m.get("sw_l2_code"))
        if code is not None and code in allowed:
            n += 1
    return n
