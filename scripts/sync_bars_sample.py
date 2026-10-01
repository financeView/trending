#!/usr/bin/env python3
"""可选：同步少量样本股到 bars.db（需网络）。"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common.bars import bars_conn, sync_symbol_bars
from scripts.common.http import RateLimiter


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--codes", default="000001.SZ,600519.SH")
    p.add_argument("--end", default="")
    args = p.parse_args(argv)
    end = (
        dt.datetime.strptime(args.end, "%Y-%m-%d").date()
        if args.end
        else dt.date.today()
    )
    conn = bars_conn()
    lim = RateLimiter(2.0)
    for code in [c.strip() for c in args.codes.split(",") if c.strip()]:
        n = sync_symbol_bars(conn, code, end, limiter=lim)
        print("[sync_bars] %s rows=%d end=%s" % (code, n, end))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
