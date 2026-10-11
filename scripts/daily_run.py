#!/usr/bin/env python3
"""P0/P0.5 daily_run：交易日历门禁 + 断点续跑 + run_meta ok 谓词。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from typing import Any, Mapping, Sequence

# repo root on sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common import calendar as cal
from scripts.common.bars import DEFAULT_BARS_DB, bars_conn
from scripts.common.hard_freeze import check_hard_freeze_stamp
from scripts.common.coverage import (
    CoverageMetrics,
    OK_PREDICATE_VERSION,
    OkDecision,
    compute_coverage_from_bars,
    evaluate_ok,
)
from scripts.common.db import (
    DEFAULT_DB,
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
from scripts.taxonomy.unmapped import UnmappedMetrics, compute_unmapped_metrics
from scripts.common.universe import (
    l2_members_map,
    load_map_version,
    load_quarantine_codes,
    load_universe_codes,
)
from scripts.metrics.aggregate import (
    MEMBER_SET,
    aggregate_l1,  # imported so tests can spy; not used for daily_l1 writes
    stub_l1_members,
    taxonomy_for_stock,
)
from scripts.metrics.l2_synth import synthesize_basket_bars
from scripts.metrics.params import MetricsParams, load_params
from scripts.metrics.peer_rs import (
    assign_peer_rs,
    basket_peer_eligible,
    stock_peer_eligible,
)
from scripts.metrics.pipeline import replay_from_ohlc
from scripts.metrics.vol_score import compute_vol_scores, turnover_from_bar

_METRICS_YAML = os.path.join(_ROOT, "config", "metrics", "a_share_daily.yaml")
_FIRST_SEEN_PATH = os.path.join(_ROOT, "data", "unmapped_first_seen.json")
_HEARTBEAT_PATH = os.path.join(os.path.dirname(DEFAULT_DB), "heartbeat.json")
_TAXONOMY_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")

_BARS_SELECT = """
SELECT trade_date, open_qfq, high_qfq, low_qfq, close_qfq,
       is_st, is_suspended, float_mv, amount, hard_freeze_flag
FROM bars
WHERE ts_code=? AND trade_date<=?
ORDER BY trade_date ASC
"""


def _parse_date(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def _heartbeat_path() -> str:
    return os.environ.get("TREND_HEARTBEAT") or _HEARTBEAT_PATH


def _load_heartbeat_taxonomy() -> dict:
    path = _heartbeat_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    tax = data.get("taxonomy") if isinstance(data, dict) else None
    return tax if isinstance(tax, dict) else {}


def _env_nonempty(name: str) -> str:
    val = os.environ.get(name)
    return val if val else ""


def _load_taxonomy_fetch() -> str:
    env = _env_nonempty("TAXONOMY_FETCH")
    if env:
        return env
    tax = _load_heartbeat_taxonomy()
    fetch = tax.get("taxonomy_fetch")
    return fetch if fetch else "ok"


def _resolve_git_sha() -> str:
    head = _env_nonempty("TAXONOMY_HEAD_SHA")
    if head:
        return head
    gsha = _env_nonempty("GITHUB_SHA")
    if gsha:
        return gsha
    tax = _load_heartbeat_taxonomy()
    fetch = tax.get("taxonomy_fetch")
    commit = str(tax.get("taxonomy_commit") or "")
    # Only successful YAML publish (`ok`); never fail/push_fail/skipped_no_diff.
    if fetch == "ok" and _TAXONOMY_COMMIT_RE.match(commit):
        return commit
    return ""


def _run_meta_unmapped_fields(
    *,
    D: dt.date,
    session_asof: dt.date,
    um: Any,
    prior_unmapped_count=None,
) -> dict:
    if D == session_asof:
        return {"unmapped_count": um.unmapped_count}  # may be None → SQL NULL
    return {"unmapped_count": prior_unmapped_count}


def _append_taxonomy_warn(
    base: str,
    *,
    ipo_alert: int | None = 0,
    taxonomy_fetch: str = "ok",
    clist_fetch: str = "ok",
    unmapped_count: int | None = None,  # noqa: ARG001 — never warns on bare count
) -> str:
    bits: list[str] = []
    if taxonomy_fetch in ("fail", "push_fail"):
        bits.append("taxonomy_fetch=%s" % taxonomy_fetch)
    if ipo_alert is not None and ipo_alert > 0:
        bits.append("ipo_unmapped_alert=%s" % ipo_alert)
    if clist_fetch == "fail":
        bits.append("clist_fetch=fail")
    if not bits:
        return base or ""
    tax = "taxonomy: " + ", ".join(bits)
    if base:
        return "%s; %s" % (base, tax)
    return tax


def _compose_asof_status_and_warn(
    decision: OkDecision,
    *,
    ipo_alert: int | None,
    taxonomy_fetch: str,
    clist_fetch: str,
) -> tuple[str, str]:
    status = decision.status  # never flip for IPO / unmapped / clist
    base = (
        decision.reason
        if decision.reason and decision.reason != "passed"
        else ""
    )
    warn = _append_taxonomy_warn(
        base,
        ipo_alert=ipo_alert or 0,
        taxonomy_fetch=taxonomy_fetch,
        clist_fetch=clist_fetch,
    )
    return status, warn


def _default_unmapped_metrics() -> UnmappedMetrics:
    return UnmappedMetrics(
        unmapped_count=None,
        ipo_unmapped_alert_count=None,
        yaml_quarantine_size=0,
        clist_fetch="ok",
    )


def resolve_session(
    date_arg: str,
    only_date: bool,
    asof_arg: str,
    asof_day: dt.date,
):
    """session_asof is asof_day / --asof; --date is replay start, not asof."""
    if only_date and not date_arg:
        raise ValueError("--only-date requires --date")
    session_asof = _parse_date(asof_arg) if asof_arg else asof_day
    if not date_arg:
        return session_asof, None
    start = _parse_date(date_arg)
    if start > session_asof:
        raise ValueError("date %s > asof %s" % (start, session_asof))
    if only_date:
        return session_asof, [start]
    return session_asof, cal.trading_days_inclusive(start, session_asof)


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
        mapped_size=universe_size,
        mapped_sync_coverage=1.0,
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


def _bar_trade_date_str(raw_td) -> str | None:
    """Normalize bar trade_date to YYYY-MM-DD (date/datetime/str)."""
    if raw_td is None:
        return None
    if isinstance(raw_td, dt.date):
        return raw_td.isoformat()[:10]
    return str(raw_td)[:10]


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
                "hard_freeze_flag": r[9],
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
        "right_side_days_natural": snap.get(
            "days_natural_after_bump", snap.get("days_natural")
        ),
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


def _basket_asof_row(
    code: str,
    members: Sequence[str],
    stock_rows: Sequence[Mapping],
    snap: Mapping | None,
    *,
    trade_date: str,
    members_total: int,
) -> dict:
    """Build one daily_l1/l2 row: engine from snap; count/amount via member_set."""
    member_set = set(members)
    warm_count = 0
    amount_sum = 0.0
    any_amount = False
    members_tradable = 0
    for r in stock_rows:
        ts = r.get("ts_code")
        if ts in member_set:
            if r.get("tag_warm_to_hot"):
                warm_count += 1
            amt = _sql_float(r.get("amount"))
            if amt is not None:
                amount_sum += amt
                any_amount = True
            if not r.get("hard_frozen") and not r.get("_is_suspended"):
                members_tradable += 1
    if snap is None:
        t = None
        right_side = None
        tag_hot = None
        tag_flat = None
        solar = None
        s_temp = None
        rs_raw = None
    else:
        t = snap.get("T")
        right_side = int(bool(snap.get("R")))
        tag_hot = int(bool(snap.get("tag_warm_to_hot")))
        tag_flat = int(bool(snap.get("tag_warm_to_flat")))
        solar = snap.get("solar_term")
        s_temp = _sql_float(snap.get("S_temp"))
        rs_raw = snap.get("RS_raw")
    return {
        "trade_date": trade_date,
        "code": code,
        "T": t,
        "S_temp": s_temp,
        "RS": None,  # filled by peer pass
        "RS_raw": rs_raw,  # ephemeral; stripped by upsert COLS
        "right_side": right_side,
        "tag_warm_to_hot": tag_hot,
        "tag_warm_to_flat": tag_flat,
        "solar_term": solar,
        "members_tradable": members_tradable,
        "members_total": members_total,
        "warm_to_hot_member_count": warm_count,
        "amount": amount_sum if any_amount else None,
        "VOL_score": None,  # baskets always null this slice (Spec C §2.3)
    }


_l2_asof_row = _basket_asof_row  # compat for tests / call sites


def _l2_trade_dates(bar_cache: Mapping[str, Sequence[Mapping]], D: dt.date) -> list[dt.date]:
    """Full trading calendar from earliest loaded bar through D (never bar-union)."""
    start: dt.date | None = None
    for records in bar_cache.values():
        for r in records:
            raw = r.get("trade_date")
            if raw is None:
                continue
            if isinstance(raw, dt.date):
                d = raw
            else:
                d = dt.date.fromisoformat(str(raw)[:10])
            if start is None or d < start:
                start = d
    if start is None:
        return []
    return cal.trading_days_inclusive(start, D)


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
        qua = load_quarantine_codes()
        min_hist = _metrics_min_history()
        stock_rows: list[dict] = []
        events: list[dict] = []
        bar_cache: dict[str, list[dict]] = {}
        td = D.isoformat()
        for ts in universe:
            records = _load_symbol_bars(bconn, ts, D)
            bar_cache[ts] = records
            if not records:
                continue
            snaps = replay_from_ohlc(params, records, min_history=min_hist)
            asof_snaps = [s for s in snaps if s.get("trade_date") == td]
            if not asof_snaps:
                continue
            snap = asof_snaps[-1]
            row = _snap_to_daily_stock(ts, snap)
            row["_is_suspended"] = bool(snap.get("is_suspended"))
            row["RS_raw"] = snap.get("RS_raw")  # ephemeral; for peer / strip on upsert
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
                        "RS": None,  # backfilled after peer
                        "detail": rec.get("detail") or {},
                    }
                )
        mapping = l2_members_map()
        for members in mapping.values():
            for ts in members:
                if ts not in bar_cache:
                    bar_cache[ts] = _load_symbol_bars(bconn, ts, D)
        dates = _l2_trade_dates(bar_cache, D)

        l2_rows: list[dict] = []
        for code, members in mapping.items():
            if not members:
                continue
            member_bars = {ts: bar_cache[ts] for ts in members if bar_cache.get(ts)}
            synth = synthesize_basket_bars(member_bars, trade_dates=dates)
            snap = None
            if synth:
                snaps = replay_from_ohlc(params, synth, min_history=min_hist)
                asof = [s for s in snaps if s.get("trade_date") == td]
                snap = asof[-1] if asof else None
            # NEVER append snap.event_records to events
            l2_rows.append(
                _basket_asof_row(
                    code,
                    members,
                    stock_rows,
                    snap,
                    trade_date=td,
                    members_total=len(members),
                )
            )

        l1_groups = stub_l1_members()
        dates_start = dates[0] if dates else None
        cache_grew_earlier = False
        for members in l1_groups.values():
            for ts in members:
                if ts not in bar_cache:
                    loaded = _load_symbol_bars(bconn, ts, D)
                    bar_cache[ts] = loaded
                    for r in loaded:
                        raw = r.get("trade_date")
                        if raw is None:
                            continue
                        if isinstance(raw, dt.date):
                            d = raw
                        else:
                            d = dt.date.fromisoformat(str(raw)[:10])
                        if dates_start is None or d < dates_start:
                            cache_grew_earlier = True
                            break
        if cache_grew_earlier:
            dates = _l2_trade_dates(bar_cache, D)

        l1_rows: list[dict] = []
        for l1_id, members in l1_groups.items():
            if not members:
                continue
            member_bars = {ts: bar_cache[ts] for ts in members if bar_cache.get(ts)}
            synth = synthesize_basket_bars(member_bars, trade_dates=dates)
            snap = None
            if synth:
                snaps = replay_from_ohlc(params, synth, min_history=min_hist)
                asof = [s for s in snaps if s.get("trade_date") == td]
                snap = asof[-1] if asof else None
            # NEVER append snap.event_records to events
            l1_rows.append(
                _basket_asof_row(
                    l1_id,
                    members,
                    stock_rows,
                    snap,
                    trade_date=td,
                    members_total=len(members),
                )
            )

        # Three separate peer universes (isolation).
        assign_peer_rs(
            stock_rows,
            eligible=lambda r: stock_peer_eligible(r, quarantine=qua),
        )
        assign_peer_rs(l2_rows, eligible=basket_peer_eligible)
        assign_peer_rs(l1_rows, eligible=basket_peer_eligible)

        # Stock own-history VOL_score on OHLC spine; baskets stay null.
        for r in stock_rows:
            records = bar_cache.get(r["ts_code"]) or []
            turnovers = [
                turnover_from_bar(b.get("amount"), b.get("float_mv"))
                for b in records
            ]
            scores = compute_vol_scores(
                turnovers,
                vol_hist=params.vol_hist,
                min_samples=params.vol_score_min_samples,
            )
            vol = None
            for i, b in enumerate(records):
                bar_td = _bar_trade_date_str(b.get("trade_date"))
                if bar_td == td:
                    vol = scores[i] if i < len(scores) else None
            r["VOL_score"] = vol

        pv = params.param_version
        for r in stock_rows:
            r["universe_id"] = "local_stock"
            r["param_version"] = pv
        for r in l2_rows:
            r["universe_id"] = "local_l2"
            r["param_version"] = pv
            r["VOL_score"] = None
        for r in l1_rows:
            r["universe_id"] = "local_l1"
            r["param_version"] = pv
            r["VOL_score"] = None

        rs_by_ts = {r["ts_code"]: r.get("RS") for r in stock_rows}
        for ev in events:
            ev["RS"] = rs_by_ts.get(ev["ts_code"])

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
    um: UnmappedMetrics | None = None,
    taxonomy_fetch: str | None = None,
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

    um = um if um is not None else _default_unmapped_metrics()
    tf = taxonomy_fetch if taxonomy_fetch is not None else _load_taxonomy_fetch()

    prior_u = None
    if D != session_asof:
        row = conn.execute(
            "SELECT unmapped_count FROM run_meta WHERE trade_date=?",
            (D.isoformat(),),
        ).fetchone()
        prior_u = row[0] if row else None

    if D == session_asof:
        status, warn = _compose_asof_status_and_warn(
            decision,
            ipo_alert=um.ipo_unmapped_alert_count,
            taxonomy_fetch=tf,
            clist_fetch=um.clist_fetch,
        )
    else:
        status = decision.status
        warn = (
            decision.reason
            if decision.reason and decision.reason != "passed"
            else ""
        )

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
                **_run_meta_unmapped_fields(
                    D=D,
                    session_asof=session_asof,
                    um=um,
                    prior_unmapped_count=prior_u,
                ),
                "tradable_count": metrics.tradable_count,
                "bar_coverage": metrics.bar_coverage,
                "computable_coverage": metrics.computable_coverage,
                "limit_coverage_asof": metrics.limit_coverage_asof,
                "open_raw_coverage_asof": metrics.open_raw_coverage_asof,
                "mapped_size": metrics.mapped_size,
                "mapped_sync_coverage": metrics.mapped_sync_coverage,
                "ok_predicate_version": OK_PREDICATE_VERSION,
                "git_sha": _resolve_git_sha(),
                "started_at": started,
                "finished_at": finished,
                "status": status,
                "warn": warn,
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
            status,
            decision.reason,
            decision.apply_limit_gate,
            metrics.bar_coverage,
            metrics.computable_coverage,
            metrics.limit_coverage_asof,
            metrics.tradable_count,
        )
    )
    return status


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="trending P0.5 daily_run")
    p.add_argument(
        "--date",
        default="",
        help="重跑起点 YYYY-MM-DD（不是 session asof；默认从 last_ok 续跑）",
    )
    p.add_argument(
        "--only-date",
        action="store_true",
        help="与 --date 联用：只跑该日",
    )
    p.add_argument(
        "--asof",
        default="",
        help="覆盖 session_asof（默认 latest_trade_day）",
    )
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

    asof_day = _parse_date(args.asof) if args.asof else cal.latest_trade_day()
    try:
        session_asof, queue_override = resolve_session(
            args.date,
            args.only_date,
            args.asof,
            asof_day,
        )
    except ValueError as e:
        print("[daily_run] %s" % e)
        return 2

    gate_day = _parse_date(args.date) if args.date else session_asof
    if not args.force_trade_day and not cal.is_trade_day(gate_day):
        print("[skip] non-trading-day %s" % gate_day)
        write_heartbeat({"job": "daily_run", "status": "skip", "date": str(gate_day)})
        return 0

    if args.date and not args.force_trade_day and not cal.is_trade_day(session_asof):
        print("[skip] non-trading-day asof %s" % session_asof)
        return 0

    queue = queue_override if queue_override is not None else build_queue(session_asof)
    if not queue:
        # ensure at least process asof when cold or already ok through asof
        if args.force_trade_day or cal.is_trade_day(session_asof):
            queue = [session_asof]
        else:
            print("[daily_run] empty queue")
            return 0

    stamp_rc = check_hard_freeze_stamp(args.bars_db or None)
    if stamp_rc != 0:
        return stamp_rc

    print("[daily_run] queue=%s" % [d.isoformat() for d in queue])
    # Spec D: one clist snapshot for session_asof; asof run_meta only.
    try:
        um = compute_unmapped_metrics(
            session_asof=session_asof,
            first_seen_path=_FIRST_SEEN_PATH,
        )
    except Exception:
        um = UnmappedMetrics(
            unmapped_count=None,
            ipo_unmapped_alert_count=None,
            yaml_quarantine_size=0,
            clist_fetch="fail",
        )
    taxonomy_fetch = _load_taxonomy_fetch()
    statuses = []
    bars_path = args.bars_db or None
    for D in queue:
        st = process_day(
            D,
            session_asof,
            stub_coverage=args.stub_coverage,
            bars_path=bars_path,
            um=um,
            taxonomy_fetch=taxonomy_fetch,
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
