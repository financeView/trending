#!/usr/bin/env python3
"""P0/P0.5 daily_run：交易日历门禁 + 断点续跑 + run_meta ok 谓词。"""
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
from scripts.common.bars import DEFAULT_BARS_DB, bars_conn
from scripts.common.coverage import (
    CoverageMetrics,
    OK_PREDICATE_VERSION,
    compute_coverage_from_bars,
    evaluate_ok,
)
from scripts.common.db import (
    append_signal_events,
    first_unfinished_trade_date,
    get_conn,
    init_schema,
    last_ok_trade_date,
    upsert_daily_l1,
    upsert_daily_l2,
    upsert_daily_stock,
    upsert_rows,
    write_heartbeat,
)
from scripts.common.universe import load_map_version, load_universe_codes
from scripts.metrics.aggregate import (
    MEMBER_SET,
    aggregate_l1,
    aggregate_l2,
    taxonomy_for_stock,
)
from scripts.metrics.params import MetricsParams, load_params
from scripts.metrics.pipeline import replay_from_ohlc

_METRICS_YAML = os.path.join(_ROOT, "config", "metrics", "a_share_daily.yaml")

_BARS_SELECT = """
SELECT trade_date, open_qfq, high_qfq, low_qfq, close_qfq,
       is_st, is_suspended, float_mv, amount
FROM bars
WHERE ts_code=? AND trade_date<=?
ORDER BY trade_date ASC
"""


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
    """离线 CI / smoke：全绿占位；真实 sync 后由 bars 统计替换。"""
    return CoverageMetrics(
        bar_coverage=1.0,
        computable_coverage=1.0,
        limit_coverage_asof=1.0,
        open_raw_coverage_asof=1.0,
        tradable_count=universe_size,
        universe_size=universe_size,
    )


def _resolve_coverage(
    D: dt.date,
    *,
    metrics: CoverageMetrics | None,
    stub_coverage: bool,
    bars_path: str | None,
) -> CoverageMetrics:
    if metrics is not None:
        return metrics
    use_stub = stub_coverage or os.environ.get("STUB_COVERAGE", "").strip() in (
        "1",
        "true",
        "True",
        "yes",
    )
    if use_stub:
        return _stub_coverage()
    bconn = bars_conn(bars_path)
    try:
        return compute_coverage_from_bars(bconn, D)
    finally:
        bconn.close()


def _sql_float(value) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def _sql_int_bool(value) -> int:
    return int(bool(value))


def load_metrics_params() -> MetricsParams:
    path = os.environ.get("METRICS_PARAMS_YAML") or _METRICS_YAML
    return load_params(path)


def _metrics_min_history() -> int | None:
    """Optional test override. Shortening this alone does not cut vol_hist=252."""
    raw = os.environ.get("METRICS_MIN_HISTORY", "").strip()
    if raw:
        return int(raw)
    return None


def _bars_db_path(bars_path: str | None) -> str | None:
    if bars_path:
        return bars_path
    if os.path.exists(DEFAULT_BARS_DB):
        return DEFAULT_BARS_DB
    return None


def _load_symbol_bars(conn, ts_code: str, D: dt.date) -> list[dict]:
    rows = conn.execute(_BARS_SELECT, (ts_code, D.isoformat())).fetchall()
    out = []
    for r in rows:
        if r[4] is None or r[2] is None or r[3] is None:
            continue
        out.append(
            {
                "trade_date": r[0],
                "open_qfq": r[1],
                "high_qfq": r[2],
                "low_qfq": r[3],
                "close_qfq": r[4],
                "is_st": r[5],
                "is_suspended": r[6],
                "float_mv": r[7],
                "amount": r[8],
            }
        )
    return out


def _snap_to_daily_stock(ts_code: str, snap: dict) -> dict:
    sw, l1 = taxonomy_for_stock(ts_code)
    return {
        "trade_date": snap["trade_date"],
        "ts_code": ts_code,
        "sw_l2_code": sw,
        "l1_id": l1,
        "T": snap.get("T"),
        "S_temp": _sql_float(snap.get("S_temp")),
        "RS": _sql_float(snap.get("RS")),
        "universe_id": "local_stock",
        "right_side": _sql_int_bool(snap.get("R")),
        "right_side_days_natural": snap.get("days_natural"),
        "right_side_days_trading": snap.get("days_trading"),
        "tag_warm_to_hot": _sql_int_bool(snap.get("tag_warm_to_hot")),
        "tag_warm_to_flat": _sql_int_bool(snap.get("tag_warm_to_flat")),
        "solar_term": snap.get("solar_term"),
        "hard_frozen": _sql_int_bool(snap.get("hard_frozen")),
        "amount": _sql_float(snap.get("amount")),
        "close_qfq": _sql_float(snap.get("close_qfq")),
        "float_mv": _sql_float(snap.get("float_mv")),
        "stage_score": _sql_float(snap.get("stage_score")),
        "stage_score_raw": _sql_float(snap.get("stage_score_raw")),
    }


def replay_metrics_cross_section(
    D: dt.date,
    *,
    bars_path: str | None,
    params: MetricsParams,
    universe: list[str],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Strategy A: replay each symbol from bars ≤D in memory; persist D only."""
    path = _bars_db_path(bars_path)
    if path is None:
        return [], [], [], []
    bconn = bars_conn(path)
    try:
        min_hist = _metrics_min_history()
        stock_rows: list[dict] = []
        events: list[dict] = []
        td = D.isoformat()
        for ts in universe:
            records = _load_symbol_bars(bconn, ts, D)
            if not records:
                continue
            snaps = replay_from_ohlc(params, records, min_history=min_hist)
            asof_snaps = [s for s in snaps if s.get("trade_date") == td]
            if not asof_snaps:
                continue
            snap = asof_snaps[-1]
            row = _snap_to_daily_stock(ts, snap)
            row["_is_suspended"] = bool(snap.get("is_suspended"))
            stock_rows.append(row)
            sw, l1 = taxonomy_for_stock(ts)
            for rec in snap.get("event_records") or []:
                events.append(
                    {
                        "trade_date": td,
                        "ts_code": ts,
                        "sw_l2_code": sw,
                        "l1_id": l1,
                        "event": rec.get("event"),
                        "T": rec.get("T"),
                        "RS": None,
                        "detail": rec.get("detail") or {},
                    }
                )
        tradable = {
            r["ts_code"]
            for r in stock_rows
            if not r.get("hard_frozen") and not r.get("_is_suspended")
        }
        tradable_rows = [r for r in stock_rows if r["ts_code"] in tradable]
        l2_rows = [
            row
            for row in aggregate_l2(tradable_rows, td)
            if row.get("members_tradable")
        ]
        l1_rows = [
            row
            for row in aggregate_l1(tradable_rows, td)
            if row.get("members_tradable")
        ]
        return stock_rows, l2_rows, l1_rows, events
    finally:
        bconn.close()


def process_day(
    D: dt.date,
    session_asof: dt.date,
    *,
    metrics: CoverageMetrics | None = None,
    stub_coverage: bool = False,
    bars_path: str | None = None,
) -> str:
    conn = get_conn()
    init_schema(conn)
    started = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    params = load_metrics_params()
    map_version = load_map_version()
    universe = load_universe_codes()
    # Metrics first: --stub-coverage only skips coverage stats, not replay.
    stock_rows, l2_rows, l1_rows, events = replay_metrics_cross_section(
        D, bars_path=bars_path, params=params, universe=universe
    )
    if stock_rows:
        upsert_daily_stock(conn, stock_rows, commit=False)
    if l2_rows:
        upsert_daily_l2(conn, l2_rows, commit=False)
    if l1_rows:
        upsert_daily_l1(conn, l1_rows, commit=False)
    if events:
        append_signal_events(conn, events, commit=False)
    conn.commit()
    metrics = _resolve_coverage(
        D, metrics=metrics, stub_coverage=stub_coverage, bars_path=bars_path
    )
    decision = evaluate_ok(D, session_asof, metrics)
    finished = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    upsert_rows(
        conn,
        "run_meta",
        [
            {
                "trade_date": D.isoformat(),
                "param_version": params.param_version,
                "map_version": map_version,
                "member_set": MEMBER_SET,
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
        "[daily_run] D=%s asof=%s status=%s reason=%s limit_gate=%s "
        "bar=%.3f comp=%.3f lim=%.3f U=%d"
        % (
            D,
            session_asof,
            decision.status,
            decision.reason,
            decision.apply_limit_gate,
            metrics.bar_coverage,
            metrics.computable_coverage,
            metrics.limit_coverage_asof,
            metrics.tradable_count,
        )
    )
    return decision.status


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="trending P0.5 daily_run")
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
    p.add_argument(
        "--stub-coverage",
        action="store_true",
        help=(
            "跳过覆盖率统计（全绿 CoverageMetrics）；仍会从 bars 重放 metrics。"
            "Actions 关掉 stub 的前提是全宇宙 sync 齐套（非本 Task 阻塞）。"
        ),
    )
    p.add_argument(
        "--bars-db",
        default="",
        help="bars.db 路径（默认 data/cache/bars.db）",
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
    bars_path = args.bars_db or None
    for D in queue:
        st = process_day(
            D,
            session_asof,
            stub_coverage=args.stub_coverage,
            bars_path=bars_path,
        )
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
