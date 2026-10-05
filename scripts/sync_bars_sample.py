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
from scripts.common.calendar import latest_trade_day
from scripts.common.http import RateLimiter
from scripts.common.universe import load_quarantine_codes, load_universe_codes


def codes_from_universe(path: str = "") -> list[str]:
    """Mapped universe minus quarantine. Empty path = production stock map."""
    if path:
        qua = load_quarantine_codes(path)
        return [c for c in load_universe_codes(path) if c not in qua]
    qua = load_quarantine_codes()
    return [c for c in load_universe_codes() if c not in qua]


def ohlc_end_row_exists(conn, ts_code: str, end: dt.date) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM bars
        WHERE ts_code=? AND trade_date=? AND close_qfq IS NOT NULL
        """,
        (ts_code, end.isoformat()),
    ).fetchone()
    return row is not None


def skip_ohlc(conn, ts_code: str, end: dt.date, min_history: int = 252) -> bool:
    """Skip fetch only if end-day OHLC exists and history is already full.

    IPOs with an end row but fewer than ``min_history`` sessions are still fetched
    (window stays end-400). Spec: 252 is a resume heuristic, not an ok gate.
    """
    if not ohlc_end_row_exists(conn, ts_code, end):
        return False
    n = conn.execute(
        """
        SELECT COUNT(*) FROM bars
        WHERE ts_code=? AND trade_date<=? AND close_qfq IS NOT NULL
        """,
        (ts_code, end.isoformat()),
    ).fetchone()[0]
    return int(n) >= int(min_history)


def skip_flags(conn, ts_code: str, end: dt.date) -> bool:
    row = conn.execute(
        """
        SELECT flag_source FROM bars WHERE ts_code=? AND trade_date=?
        """,
        (ts_code, end.isoformat()),
    ).fetchone()
    return bool(row and row[0])


def write_sync_complete(complete: bool, elapsed_min: float = 0.0) -> None:
    flag = "true" if complete else "false"
    deferred = "true" if (complete and elapsed_min > 200) else "false"
    print(
        "[sync_bars] sync_complete=%s elapsed_min=%.1f run_deferred=%s"
        % (flag, elapsed_min, deferred)
    )
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("sync_complete=%s\n" % flag)
            f.write("sync_elapsed_min=%.1f\n" % elapsed_min)
            f.write("run_deferred=%s\n" % deferred)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--codes", default="", help="Comma ts_codes; empty = mapped universe")
    p.add_argument(
        "--from-universe",
        default="",
        help="Test/fixture YAML (overrides --codes). Production omits this.",
    )
    p.add_argument("--end", default="")
    p.add_argument("--max-codes", type=int, default=0, help="0 = no cap")
    p.add_argument("--time-budget-min", type=float, default=0, help="0 = no budget")
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
        else latest_trade_day()
    )
    if args.from_universe:
        codes = codes_from_universe(args.from_universe)
    elif args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        codes = codes_from_universe()
    codes = sorted(set(codes))
    conn = bars_conn()
    lim = RateLimiter(2.0)
    started = dt.datetime.utcnow()
    complete = True
    worked = 0
    for code in codes:
        if args.time_budget_min and args.time_budget_min > 0:
            elapsed = (dt.datetime.utcnow() - started).total_seconds() / 60.0
            if elapsed >= args.time_budget_min:
                complete = False
                print("[sync_bars] time budget hit after %.1f min" % elapsed)
                break
        need_ohlc = not args.skip_ohlc and not skip_ohlc(conn, code, end)
        need_flags = not args.skip_flags and not skip_flags(conn, code, end)
        if not need_ohlc and not need_flags:
            continue
        if args.max_codes and args.max_codes > 0 and worked >= args.max_codes:
            complete = False
            print("[sync_bars] max-codes=%d hit; remaining work" % args.max_codes)
            break
        if need_ohlc:
            n = sync_symbol_bars(conn, code, end, limiter=lim)
            print("[sync_bars] ohlc %s rows=%d end=%s" % (code, n, end))
        if need_flags:
            nf = sync_baostock_flags(conn, code, end, limiter=lim)
            print("[sync_bars] flags %s rows=%d" % (code, nf))
        worked += 1
    if args.with_limits and complete:
        asof = latest_trade_day()
        if end != asof:
            print(
                "[sync_bars] skip --with-limits (end=%s != asof %s)"
                % (end, asof)
            )
        else:
            try:
                nl = sync_em_limits_asof(conn, end, ts_codes=codes, limiter=lim)
                print("[sync_bars] limits asof=%s rows=%d" % (end, nl))
            except Exception as e:  # noqa: BLE001 — EM best-effort; OHLC/flags already persisted
                print("[sync_bars] warn: limits skipped: %s" % e, file=sys.stderr)
    conn.close()
    elapsed_min = (dt.datetime.utcnow() - started).total_seconds() / 60.0
    write_sync_complete(complete, elapsed_min)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
