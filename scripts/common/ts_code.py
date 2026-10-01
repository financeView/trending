"""Tushare 式 ts_code 与各免费源符号互转。"""
from __future__ import annotations

import re

_TS_RE = re.compile(r"^(\d{6})\.(SH|SZ)$")


def is_ts_code(code: str) -> bool:
    return bool(_TS_RE.match(code or ""))


def to_ts_code(raw: str) -> str:
    """接受 000001 / sz000001 / SH600000 / 000001.SZ 等，输出 XXXXXX.SH|SZ。"""
    s = (raw or "").strip().upper()
    if _TS_RE.match(s):
        return s
    m = re.match(r"^(SH|SZ)(\d{6})$", s)
    if m:
        return "%s.%s" % (m.group(2), m.group(1))
    m = re.match(r"^(\d{6})$", s)
    if m:
        num = m.group(1)
        if num.startswith(("5", "6", "9")):
            return num + ".SH"
        return num + ".SZ"
    m = re.match(r"^(SH|SZ)(\d{6})$", s.replace(".", ""))
    if m:
        return "%s.%s" % (m.group(2), m.group(1))
    raise ValueError("cannot parse ts_code from %r" % raw)


def to_sina_symbol(ts_code: str) -> str:
    code = to_ts_code(ts_code)
    num, mkt = code.split(".")
    return ("sh" if mkt == "SH" else "sz") + num


def to_baostock_code(ts_code: str) -> str:
    code = to_ts_code(ts_code)
    num, mkt = code.split(".")
    return ("sh." if mkt == "SH" else "sz.") + num


def to_em_symbol(ts_code: str) -> str:
    """东财多数个股接口用纯 6 位。"""
    return to_ts_code(ts_code).split(".")[0]
