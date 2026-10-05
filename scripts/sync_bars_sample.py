#!/usr/bin/env python3
"""可选：同步少量样本股到 bars.db（需网络）。

默认：sina OHLC + BaoStock flags；--with-limits 时再拉东财当日涨跌停。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common.bars import (
    bars_conn,
    sync_baostock_flags,
    sync_em_limits_asof,
    sync_symbol_bars,
)
from scripts.common.http import RateLimiter
from scripts.common.universe import load_universe_codes


def codes_from_universe(path: str) -> list[str]:
    """Members from classification universe YAML (quarantine excluded)."""
    return load_universe_codes(path)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--codes", default="000001.SZ,600519.SH")
    p.add_argument(
        "--from-universe",
        default="",
        help="Read member codes from universe YAML (overrides --codes)",
    )
    p.add_argument("--end", default="")
    p.add_argument(
        "--with-limits",
        action="store_true",
        help="同步东财 f51/f52 涨跌停到 --end 当日（仅 asof 有意义）",
    )
    p.add_argument(
        "--skip-ohlc",
        action="store_true",
        help="跳过 sina OHLC（仅 flags / limits）",
    )
    p.add_argument(
        "--skip-flags",
        action="store_true",
        help="跳过 BaoStock is_st / is_suspended",
    )
    args = p.parse_args(argv)
    end = (
        dt.datetime.strptime(args.end, "%Y-%m-%d").date()
        if args.end
        else dt.date.today()
    )
    if args.from_universe:
        codes = codes_from_universe(args.from_universe)
    else:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    conn = bars_conn()
    lim = RateLimiter(2.0)
    for code in codes:
        if not args.skip_ohlc:
            n = sync_symbol_bars(conn, code, end, limiter=lim)
            print("[sync_bars] ohlc %s rows=%d end=%s" % (code, n, end))
        if not args.skip_flags:
            nf = sync_baostock_flags(conn, code, end, limiter=lim)
            print("[sync_bars] flags %s rows=%d" % (code, nf))
    if args.with_limits:
        nl = sync_em_limits_asof(conn, end, ts_codes=codes, limiter=lim)
        print("[sync_bars] limits asof=%s rows=%d" % (end, nl))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
