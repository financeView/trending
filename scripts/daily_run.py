#!/usr/bin/env python3
"""P0 daily_run：交易日历门禁 + 断点续跑 + run_meta ok 谓词。"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

# repo root on sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common import calendar as cal
from scripts.common.coverage import (
    COMPUTABLE_COVERAGE_MIN,
    CoverageMetrics,
    OK_PREDICATE_VERSION,
    evaluate_ok,
)
from scripts.common.db import (
    first_unfinished_trade_date,
    get_conn,
    init_schema,
    last_ok_trade_date,
    upsert_rows,
    write_heartbeat,
)


def _parse_date(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def build_queue(session_asof: dt.date) -> list[dt.date]:
    """从续跑起点到 asof 的交易日队列。

    起点：若存在首个非 ok 日 → 该日；否则 next_trade_date(连续 ok 末尾)；
    冷启动（无 run_meta）→ session_asof。
    """
    conn = get_conn()
    init_schema(conn)
    hole = first_unfinished_trade_date(conn)
    last = last_ok_trade_date(conn)
    conn.close()
    if hole:
        start = _parse_date(hole)
    elif last:
        start = cal.next_trade_date(_parse_date(last))
        if start is None:
            return []
    else:
        # cold start: only asof (batch backfill later)
        start = session_asof
    if start > session_asof:
        return []
    return cal.trading_days_inclusive(start, session_asof)


def _stub_coverage(universe_size: int = 100) -> CoverageMetrics:
    """P0 offline/smoke：全绿占位；真实 sync 后由统计替换。"""
    return CoverageMetrics(
        bar_coverage=1.0,
        computable_coverage=1.0,
        limit_coverage_asof=1.0,
        open_raw_coverage_asof=1.0,
        tradable_count=universe_size,
        universe_size=universe_size,
    )


def process_day(
    D: dt.date,
    session_asof: dt.date,
    *,
    metrics: CoverageMetrics | None = None,
) -> str:
    conn = get_conn()
    init_schema(conn)
    started = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    if metrics is None:
        metrics = _stub_coverage()
    decision = evaluate_ok(D, session_asof, metrics)
    finished = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    upsert_rows(
        conn,
        "run_meta",
        [
            {
                "trade_date": D.isoformat(),
                "param_version": "p0-stub",
                "map_version": "p0-stub",
                "member_set": "tradable",
                "universe_size": metrics.universe_size,
                "unmapped_count": 0,
                "tradable_count": metrics.tradable_count,
                "bar_coverage": metrics.bar_coverage,
                "computable_coverage": metrics.computable_coverage,
                "limit_coverage_asof": metrics.limit_coverage_asof,
                "open_raw_coverage_asof": metrics.open_raw_coverage_asof,
                "ok_predicate_version": OK_PREDICATE_VERSION,
                "git_sha": os.environ.get("GITHUB_SHA", ""),
                "started_at": started,
                "finished_at": finished,
                "status": decision.status,
                "warn": decision.reason if not decision.ok else "",
            }
        ],
    )
    conn.close()
    print(
        "[daily_run] D=%s asof=%s status=%s reason=%s limit_gate=%s"
        % (D, session_asof, decision.status, decision.reason, decision.apply_limit_gate)
    )
    return decision.status


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="trending P0 daily_run")
    p.add_argument("--date", default="", help="YYYY-MM-DD session asof（默认最近交易日）")
    p.add_argument(
        "--force-trade-day",
        action="store_true",
        help="跳过交易日历门禁（仅测试）",
    )
    p.add_argument(
        "--offline-calendar",
        action="store_true",
        help="仅用 data/cache/trade_dates.json，不访问网络",
    )
    args = p.parse_args(argv)

    if args.offline_calendar:
        # force load from file only
        path = cal._repo_cache_file()
        if not os.path.exists(path):
            print("[daily_run] offline-calendar 需要 %s" % path)
            return 2
        cal.clear_trade_date_cache()
        # trade_dates() will try network then file; poison network by using load
        import json

        with open(path, encoding="utf-8") as f:
            cal.load_trade_dates_from_list(json.load(f))

    if args.date:
        session_asof = _parse_date(args.date)
    else:
        session_asof = cal.latest_trade_day()

    if not args.force_trade_day and not cal.is_trade_day(session_asof):
        print("[skip] non-trading-day %s" % session_asof)
        write_heartbeat({"job": "daily_run", "status": "skip", "date": str(session_asof)})
        return 0

    if not args.force_trade_day and args.date and not cal.is_trade_day(session_asof):
        print("[skip] non-trading-day %s" % session_asof)
        return 0

    queue = build_queue(session_asof)
    if not queue:
        # ensure at least process asof when cold or already ok through asof
        if args.force_trade_day or cal.is_trade_day(session_asof):
            queue = [session_asof]
        else:
            print("[daily_run] empty queue")
            return 0

    print("[daily_run] queue=%s" % [d.isoformat() for d in queue])
    statuses = []
    for D in queue:
        st = process_day(D, session_asof)
        statuses.append(st)
        if st != "ok":
            print("[daily_run] stop queue at %s status=%s (no skip past gap)" % (D, st))
            break

    write_heartbeat(
        {
            "job": "daily_run",
            "status": "ok" if statuses and statuses[-1] == "ok" else "partial",
            "asof": session_asof.isoformat(),
            "days": [d.isoformat() for d in queue[: len(statuses)]],
            "statuses": statuses,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
