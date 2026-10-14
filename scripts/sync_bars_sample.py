#!/usr/bin/env python3
"""可选：同步少量样本股到 bars.db（需网络）。

默认：sina OHLC + BaoStock flags；--with-limits 时再拉东财当日涨跌停。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from contextlib import ExitStack

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common.bars import (
    DEFAULT_BARS_DB,
    baostock_session,
    bars_conn,
    is_baostock_session_poison,
    sync_baostock_flags,
    sync_em_float_mv_asof,
    sync_em_limits_asof,
    sync_symbol_bars,
)
from scripts.common.calendar import latest_trade_day
from scripts.common.http import RateLimiter
from scripts.common.sync_status import write_sync_status
from scripts.common.universe import load_quarantine_codes, load_universe_codes

# Probe one mapped name in Actions logs (does not change skip rules).
_DIAG_SAMPLE_CODE = "300897.SZ"

# Poison reopen budget; then skip remaining flags (no per-ticker login storm).
_FLAGS_POISON_REOPEN_MAX = 3
_FLAGS_POISON_BACKOFFS_SEC = (5.0, 15.0, 30.0)


def flags_session_policy(*, batch_ok: bool, circuit_open: bool) -> tuple[bool, bool]:
    """Return (manage_session, flags_disabled).

    Batch owns login when healthy. Never fall back to per-ticker manage_session
    after batch failure — that login-storms anonymous Baostock on tip cold sync.
    """
    if circuit_open or not batch_ok:
        return False, True
    return False, False


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


def ohlc_skip_gap(conn, ts_code: str, end: dt.date, min_history: int = 252):
    """Why OHLC cannot skip: ``miss_ohlc_end`` | ``ohlc_hist_short``; None = ok to skip."""
    if not ohlc_end_row_exists(conn, ts_code, end):
        return "miss_ohlc_end"
    n = conn.execute(
        """
        SELECT COUNT(*) FROM bars
        WHERE ts_code=? AND trade_date<=? AND close_qfq IS NOT NULL
        """,
        (ts_code, end.isoformat()),
    ).fetchone()[0]
    if int(n) < int(min_history):
        return "ohlc_hist_short"
    return None


def skip_ohlc(conn, ts_code: str, end: dt.date, min_history: int = 252) -> bool:
    """Skip fetch only if end-day OHLC exists and history is already full.

    IPOs with an end row but fewer than ``min_history`` sessions are still fetched
    (window stays end-400). Spec: 252 is a resume heuristic, not an ok gate.
    """
    return ohlc_skip_gap(conn, ts_code, end, min_history) is None


def skip_flags(conn, ts_code: str, end: dt.date) -> bool:
    row = conn.execute(
        """
        SELECT flag_source FROM bars WHERE ts_code=? AND trade_date=?
        """,
        (ts_code, end.isoformat()),
    ).fetchone()
    return bool(row and row[0])


def end_day_coverage(conn, codes: list[str], end: dt.date) -> dict:
    """Mapped-universe coverage on ``end`` (OHLC / flags / both)."""
    end_s = end.isoformat()
    want = set(codes)
    ohlc_codes = {
        r[0]
        for r in conn.execute(
            """
            SELECT ts_code FROM bars
            WHERE trade_date=? AND close_qfq IS NOT NULL
            """,
            (end_s,),
        )
        if r[0] in want
    }
    flag_codes = {
        r[0]
        for r in conn.execute(
            """
            SELECT ts_code FROM bars
            WHERE trade_date=? AND flag_source IS NOT NULL AND flag_source != ''
            """,
            (end_s,),
        )
        if r[0] in want
    }
    both = ohlc_codes & flag_codes
    max_td = conn.execute("SELECT MAX(trade_date) FROM bars").fetchone()[0]
    max_flag_td = conn.execute(
        """
        SELECT MAX(trade_date) FROM bars
        WHERE flag_source IS NOT NULL AND flag_source != ''
        """
    ).fetchone()[0]
    return {
        "universe": len(want),
        "end": end_s,
        "ohlc": len(ohlc_codes),
        "flags": len(flag_codes),
        "both": len(both),
        "max_trade_date": max_td,
        "max_flag_trade_date": max_flag_td,
    }


def print_bars_preflight(
    conn,
    codes: list[str],
    end: dt.date,
    *,
    session_asof: dt.date,
    bars_path: str,
    sample_code: str = _DIAG_SAMPLE_CODE,
) -> None:
    """Restore/sync entry diagnostics — path, integrity, end-day coverage, sample probe."""
    path = os.path.abspath(bars_path)
    size = os.path.getsize(path) if os.path.isfile(path) else -1
    try:
        qchk = conn.execute("PRAGMA quick_check").fetchone()[0]
    except Exception as e:  # noqa: BLE001
        qchk = "error:%s" % e
    cov = end_day_coverage(conn, codes, end)
    print(
        "[sync_bars] diag preflight path=%s size_bytes=%d quick_check=%s "
        "end=%s session_asof=%s universe=%d end_ohlc=%d end_flags=%d "
        "end_tip_both=%d max_trade_date=%s max_flag_trade_date=%s"
        % (
            path,
            size,
            qchk,
            cov["end"],
            session_asof.isoformat(),
            cov["universe"],
            cov["ohlc"],
            cov["flags"],
            cov["both"],
            cov["max_trade_date"],
            cov["max_flag_trade_date"],
        )
    )
    probe = sample_code if sample_code in set(codes) else (codes[0] if codes else "")
    if not probe:
        return
    end_s = end.isoformat()
    row = conn.execute(
        """
        SELECT close_qfq, flag_source FROM bars WHERE ts_code=? AND trade_date=?
        """,
        (probe, end_s),
    ).fetchone()
    hist_n = conn.execute(
        """
        SELECT COUNT(*) FROM bars
        WHERE ts_code=? AND trade_date<=? AND close_qfq IS NOT NULL
        """,
        (probe, end_s),
    ).fetchone()[0]
    max_td = conn.execute(
        "SELECT MAX(trade_date) FROM bars WHERE ts_code=?", (probe,)
    ).fetchone()[0]
    max_flag_td = conn.execute(
        """
        SELECT MAX(trade_date) FROM bars
        WHERE ts_code=? AND flag_source IS NOT NULL AND flag_source != ''
        """,
        (probe,),
    ).fetchone()[0]
    gap = ohlc_skip_gap(conn, probe, end)
    print(
        "[sync_bars] diag sample %s end=%s close_qfq=%s flag_source=%s "
        "hist_ohlc_le_end=%s max_trade_date=%s max_flag_trade_date=%s "
        "skip_ohlc=%s skip_flags=%s ohlc_gap=%s"
        % (
            probe,
            end_s,
            None if not row else row[0],
            None if not row else row[1],
            int(hist_n),
            max_td,
            max_flag_td,
            skip_ohlc(conn, probe, end),
            skip_flags(conn, probe, end),
            gap,
        )
    )


def run_spec_e_passes(conn, codes, *, session_asof: dt.date) -> None:
    from scripts.common.bars import ensure_bars_columns
    from scripts.common.board_calc import apply_board_calc
    from scripts.common.hard_freeze import (
        apply_hard_freeze_flags,
        load_hard_freeze_pass_config,
        write_hard_freeze_pass_meta,
    )
    from scripts.eval.costs import load_costs

    ensure_bars_columns(conn)
    cfg = load_hard_freeze_pass_config()
    if codes:
        nf = apply_hard_freeze_flags(conn, codes, n=cfg.min_suspend_days)
        write_hard_freeze_pass_meta(
            conn,
            n=cfg.min_suspend_days,
            param_version=cfg.param_version,
            rows_touched=nf,
        )
        if nf:
            print("[sync_bars] hard_freeze rows=%d" % nf)
    try:
        costs = load_costs()
        nb = apply_board_calc(
            conn, codes, session_asof=session_asof, limit_rule=costs.limit_rule
        )
        if nb:
            print("[sync_bars] board_calc rows=%d" % nb)
    except Exception as e:  # noqa: BLE001
        print("[sync_bars] warn: board_calc skipped: %s" % e, file=sys.stderr)


def write_sync_complete(
    complete: bool, elapsed_min: float = 0.0, *, session_asof: str
) -> None:
    """Success-end: GITHUB_OUTPUT + local sync_status.json. Spec F: no run_deferred."""
    flag = "true" if complete else "false"
    print("[sync_bars] sync_complete=%s elapsed_min=%.1f" % (flag, elapsed_min))
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("sync_complete=%s\n" % flag)
            f.write("sync_elapsed_min=%.1f\n" % elapsed_min)
    write_sync_status(
        sync_complete=bool(complete),
        session_asof=session_asof,
        elapsed_min=float(elapsed_min),
    )


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
        help="同步东财涨跌停(f51/f52)与流通市值(f21)到 --end 当日（仅 asof 有意义）",
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
    p.add_argument(
        "--asof",
        default="",
        help="session_asof YYYY-MM-DD (default: latest_trade_day); never use --end",
    )
    args = p.parse_args(argv)
    end = (
        dt.datetime.strptime(args.end, "%Y-%m-%d").date()
        if args.end
        else latest_trade_day()
    )
    session_asof = (
        dt.datetime.strptime(args.asof, "%Y-%m-%d").date()
        if args.asof
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
    row_db = conn.execute("PRAGMA database_list").fetchone()
    bars_path = (row_db[2] if row_db and row_db[2] else "") or os.path.abspath(
        DEFAULT_BARS_DB
    )
    asof_s = session_asof.isoformat()
    write_sync_status(sync_complete=False, session_asof=asof_s, elapsed_min=0.0)
    print_bars_preflight(
        conn, codes, end, session_asof=session_asof, bars_path=bars_path
    )
    # OHLC can stay aggressive; baostock TCP needs a slower dedicated limiter.
    lim = RateLimiter(4.0)
    lim_flags = RateLimiter(1.2)
    started = dt.datetime.utcnow()
    complete = True
    worked = 0
    skipped = 0
    failed_ohlc = 0
    failed_flags = 0
    reason_skippable = 0
    reason_miss_ohlc_end = 0
    reason_ohlc_hist_short = 0
    reason_miss_flags = 0
    bs_sess = None
    flags_circuit = False
    poison_reopens = 0
    with ExitStack() as stack:

        def _close_bs_batch() -> None:
            nonlocal bs_sess
            if bs_sess is None:
                return
            try:
                stack.pop_all().close()
            except Exception as close_e:  # noqa: BLE001
                print(
                    "[sync_bars] warn: baostock batch close: %s" % close_e,
                    file=sys.stderr,
                )
            bs_sess = None

        def _open_bs_batch() -> bool:
            nonlocal bs_sess, flags_circuit
            try:
                bs_sess = stack.enter_context(baostock_session())
                return True
            except Exception as e:  # noqa: BLE001
                bs_sess = None
                print(
                    "[sync_bars] warn: baostock batch login failed (%s); "
                    "disabling flags for remainder (no per-ticker login)"
                    % e,
                    file=sys.stderr,
                )
                flags_circuit = True
                return False

        if not args.skip_flags:
            _open_bs_batch()
        for code in codes:
            if args.time_budget_min and args.time_budget_min > 0:
                elapsed = (dt.datetime.utcnow() - started).total_seconds() / 60.0
                if elapsed >= args.time_budget_min:
                    complete = False
                    print("[sync_bars] time budget hit after %.1f min" % elapsed)
                    break
            # Gate must stay on skip_ohlc (tests monkeypatch it); gap is diag-only.
            need_ohlc = not args.skip_ohlc and not skip_ohlc(conn, code, end)
            need_flags = (
                not args.skip_flags
                and not flags_circuit
                and not skip_flags(conn, code, end)
            )
            if not need_ohlc and not need_flags:
                skipped += 1
                reason_skippable += 1
                continue
            if need_ohlc:
                gap = ohlc_skip_gap(conn, code, end)
                if gap == "miss_ohlc_end":
                    reason_miss_ohlc_end += 1
                elif gap == "ohlc_hist_short":
                    reason_ohlc_hist_short += 1
            if need_flags:
                reason_miss_flags += 1
            if args.max_codes and args.max_codes > 0 and worked >= args.max_codes:
                complete = False
                print("[sync_bars] max-codes=%d hit; remaining work" % args.max_codes)
                break
            if need_ohlc:
                try:
                    n = sync_symbol_bars(conn, code, end, limiter=lim)
                    print("[sync_bars] ohlc %s rows=%d end=%s" % (code, n, end))
                except Exception as e:  # noqa: BLE001 — one dead name must not kill the job
                    failed_ohlc += 1
                    print(
                        "[sync_bars] warn: ohlc %s skipped: %s" % (code, e),
                        file=sys.stderr,
                    )
            if need_flags:
                _, flags_disabled = flags_session_policy(
                    batch_ok=bs_sess is not None, circuit_open=flags_circuit
                )
                if flags_disabled or bs_sess is None:
                    # Circuit / missing batch: skip flags; never manage_session=True.
                    pass
                else:
                    try:
                        nf = sync_baostock_flags(
                            conn,
                            code,
                            end,
                            limiter=lim_flags,
                            manage_session=False,
                            session=bs_sess,
                        )
                        print("[sync_bars] flags %s rows=%d" % (code, nf))
                    except Exception as e:  # noqa: BLE001
                        failed_flags += 1
                        print(
                            "[sync_bars] warn: flags %s skipped: %s" % (code, e),
                            file=sys.stderr,
                        )
                        if is_baostock_session_poison(e):
                            _close_bs_batch()
                            if poison_reopens >= _FLAGS_POISON_REOPEN_MAX:
                                flags_circuit = True
                                print(
                                    "[sync_bars] warn: baostock poison reopen "
                                    "budget exhausted; skipping remaining flags",
                                    file=sys.stderr,
                                )
                            else:
                                delay = _FLAGS_POISON_BACKOFFS_SEC[
                                    min(
                                        poison_reopens,
                                        len(_FLAGS_POISON_BACKOFFS_SEC) - 1,
                                    )
                                ]
                                print(
                                    "[sync_bars] warn: baostock session poisoned; "
                                    "backoff %.0fs then reopen (%d/%d)"
                                    % (
                                        delay,
                                        poison_reopens + 1,
                                        _FLAGS_POISON_REOPEN_MAX,
                                    ),
                                    file=sys.stderr,
                                )
                                time.sleep(delay)
                                if _open_bs_batch():
                                    poison_reopens += 1
                                # else flags_circuit already set inside _open_bs_batch
            worked += 1
            if worked % 100 == 0:
                elapsed = (dt.datetime.utcnow() - started).total_seconds() / 60.0
                print(
                    "[sync_bars] progress worked=%d skipped=%d elapsed_min=%.1f"
                    % (worked, skipped, elapsed)
                )
    print(
        "[sync_bars] diag reasons skippable=%d miss_ohlc_end=%d "
        "ohlc_hist_short=%d miss_flags=%d"
        % (
            reason_skippable,
            reason_miss_ohlc_end,
            reason_ohlc_hist_short,
            reason_miss_flags,
        )
    )
    post = end_day_coverage(conn, codes, end)
    print(
        "[sync_bars] diag postflight end=%s end_ohlc=%d end_flags=%d "
        "end_tip_both=%d max_trade_date=%s max_flag_trade_date=%s"
        % (
            post["end"],
            post["ohlc"],
            post["flags"],
            post["both"],
            post["max_trade_date"],
            post["max_flag_trade_date"],
        )
    )
    print(
        "[sync_bars] loop done worked=%d skipped=%d failed_ohlc=%d failed_flags=%d "
        "complete=%s"
        % (worked, skipped, failed_ohlc, failed_flags, complete)
    )
    if args.with_limits and complete:
        if end != session_asof:
            print(
                "[sync_bars] skip --with-limits (end=%s != asof %s)"
                % (end, session_asof)
            )
        else:
            try:
                nl = sync_em_limits_asof(conn, end, ts_codes=codes, limiter=lim)
                print("[sync_bars] limits asof=%s rows=%d" % (end, nl))
            except Exception as e:  # noqa: BLE001
                print("[sync_bars] warn: limits skipped: %s" % e, file=sys.stderr)
            try:
                nm = sync_em_float_mv_asof(conn, end, ts_codes=codes, limiter=lim)
                print("[sync_bars] float_mv asof=%s rows=%d" % (end, nm))
            except Exception as e:  # noqa: BLE001
                print("[sync_bars] warn: float_mv skipped: %s" % e, file=sys.stderr)

    # Spec E: full mapped U (ignore --codes subset); keep conn open
    if args.from_universe:
        pass_codes = codes_from_universe(args.from_universe)
    else:
        pass_codes = codes_from_universe()
    pass_codes = sorted(set(pass_codes))
    try:
        if not args.from_universe and not pass_codes:
            print("[sync_bars] error: empty mapped universe", file=sys.stderr)
            return 1
        run_spec_e_passes(conn, pass_codes, session_asof=session_asof)
    except Exception as e:  # noqa: BLE001
        print("[sync_bars] error: hard_freeze/stamp failed: %s" % e, file=sys.stderr)
        write_sync_status(sync_complete=False, session_asof=asof_s, elapsed_min=0.0)
        return 1
    finally:
        conn.close()
    elapsed_min = (dt.datetime.utcnow() - started).total_seconds() / 60.0
    write_sync_complete(complete, elapsed_min, session_asof=asof_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
