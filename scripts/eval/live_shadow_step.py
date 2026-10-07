#!/usr/bin/env python3
"""Track L: consume persisted signal_event into paper_fill (ops P2)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common.bars import DEFAULT_BARS_DB, load_ohlc_limits
from scripts.common.calendar import latest_trade_day, prev_trade_date
from scripts.common.db import (
    consumed_signal_sides,
    get_conn,
    init_schema,
    insert_paper_fills,
    paper_fill_keys_on_date,
)
from scripts.eval.costs import load_costs
from scripts.eval.fill_day import fill_day
from scripts.eval.shadow_store import load_shadow_book, save_shadow_book
from scripts.issues.update_l1_issues import (
    _heartbeat_job_view,
    trade_date_from_heartbeat,
)


def _parse(d: str) -> date:
    return date.fromisoformat(d)


def live_allowed(conn, T: str, confirm: Optional[str]) -> tuple[bool, str]:
    """L runs only if intent day T is ok. Confirm day: skip only if a row exists and is not ok."""
    row = conn.execute(
        "SELECT status FROM run_meta WHERE trade_date=?", (T,)
    ).fetchone()
    if row is None:
        return False, "missing_run_meta"
    if row[0] != "ok":
        return False, row[0]
    if confirm:
        prev = conn.execute(
            "SELECT status FROM run_meta WHERE trade_date=?", (confirm,)
        ).fetchone()
        if prev is not None and prev[0] != "ok":
            return False, "confirm_not_ok"
    return True, "ok"


def candidate_bars_ready(bars: dict, codes: list) -> bool:
    """Skip the whole L day when no candidate has open_raw+limits (do not data_gap-consume)."""
    if not codes:
        return True
    for ts in codes:
        bar = bars.get(ts) or {}
        if bar.get("open_raw") is None:
            continue
        if bar.get("limit_up") is None or bar.get("limit_down") is None:
            continue
        return True
    return False


def heartbeat_asof_dates(path: Optional[str] = None) -> tuple[list, str]:
    """All processed trade days in heartbeat.days (catch-up prefix), else last asof."""
    asof, reason = trade_date_from_heartbeat(path)
    if reason == "skip" or not asof:
        return [], reason
    hb = path
    if hb is None:
        from scripts.common.db import DEFAULT_DB

        hb = os.path.join(os.path.dirname(DEFAULT_DB), "heartbeat.json")
    days: list = []
    if os.path.exists(hb):
        try:
            data = json.loads(open(hb, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            data = {}
        view = _heartbeat_job_view(data)
        days = [str(d) for d in (view.get("days") or [])]
    if days:
        return days, "ok"
    return [str(asof)], "ok"


def _active_signals(conn, trade_date: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, trade_date, ts_code, event, T, RS, detail
        FROM signal_event
        WHERE trade_date=? AND superseded_by IS NULL
          AND event IN ('ENTER_RIGHT','EXIT_RIGHT')
        """,
        (trade_date,),
    ).fetchall()
    out = []
    for r in rows:
        detail = r[6]
        if isinstance(detail, str) and detail:
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                detail = {}
        out.append(
            {
                "id": r[0],
                "trade_date": r[1],
                "ts_code": r[2],
                "event": r[3],
                "T": r[4],
                "RS": r[5],
                "detail": detail or {},
            }
        )
    return out


def run_asof(
    T: str,
    *,
    dry_run: bool = False,
    db_path: Optional[str] = None,
    bars_path: Optional[str] = None,
) -> int:
    if db_path:
        os.environ["TREND_DB"] = db_path
    conn = get_conn()
    init_schema(conn)
    confirm = None
    try:
        prev = prev_trade_date(_parse(T))
    except ValueError:
        print("[shadow] skip live_shadow (not_on_calendar) asof=%s" % T)
        conn.close()
        return 0
    if prev is not None:
        confirm = prev.isoformat()
    ok, why = live_allowed(conn, T, confirm)
    if not ok:
        print("[shadow] skip live_shadow (%s) asof=%s" % (why, T))
        conn.close()
        return 0

    costs = load_costs()
    book = load_shadow_book(conn, costs)
    sigs = _active_signals(conn, confirm or T)
    consumed = consumed_signal_sides(conn)

    def _side_for(ev: str) -> str:
        return "buy" if ev == "ENTER_RIGHT" else "sell"

    pending = [
        s
        for s in sigs
        if s.get("id") is None or (int(s["id"]), _side_for(s["event"])) not in consumed
    ]
    codes = sorted({s["ts_code"] for s in pending} | set(book.positions) | {p.ts_code for p in book.pending_sells})
    bars = load_ohlc_limits(bars_path or DEFAULT_BARS_DB, T, codes)
    if not candidate_bars_ready(bars, codes):
        print("[shadow] skip live_shadow (missing_bars) asof=%s" % T)
        conn.close()
        return 0
    ver_day = confirm or T
    ver = conn.execute(
        "SELECT param_version, map_version FROM run_meta WHERE trade_date=?",
        (ver_day,),
    ).fetchone()
    if ver is None:
        ver = conn.execute(
            "SELECT param_version, map_version FROM run_meta WHERE trade_date=?",
            (T,),
        ).fetchone()
    param_v = ver[0] if ver else None
    map_v = ver[1] if ver else None
    fills = fill_day(
        T,
        pending,
        book,
        bars,
        costs,
        track="L",
        param_version=param_v,
        map_version=map_v,
        run_id="shadow-%s" % T,
        skip_event_days=paper_fill_keys_on_date(conn, T),
    )
    print("[shadow] asof=%s fills=%d" % (T, len(fills)))
    if dry_run:
        conn.close()
        return 0
    insert_paper_fills(conn, fills, commit=False)
    save_shadow_book(conn, book, commit=False)
    conn.commit()
    conn.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Live shadow fill_day for one asof")
    p.add_argument("--asof", default="", help="YYYY-MM-DD or today")
    p.add_argument("--from-heartbeat", action="store_true")
    p.add_argument("--heartbeat", default="", help="heartbeat.json path")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--db", default="")
    p.add_argument("--bars-db", default="")
    args = p.parse_args(argv)
    hb = args.heartbeat or None
    if args.from_heartbeat or not args.asof:
        dates, reason = heartbeat_asof_dates(hb)
        if reason == "skip" or not dates:
            print("[shadow] heartbeat %s; skip" % reason)
            return 0
        rc = 0
        for d in dates:
            rc = run_asof(
                d,
                dry_run=args.dry_run,
                db_path=args.db or None,
                bars_path=args.bars_db or None,
            )
        return rc
    asof = args.asof
    if asof == "today":
        asof = latest_trade_day().isoformat()
    return run_asof(
        asof,
        dry_run=args.dry_run,
        db_path=args.db or None,
        bars_path=args.bars_db or None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
