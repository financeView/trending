"""market-data-contract §7.2 ok 谓词 + 从 bars 统计 CoverageMetrics。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

from scripts.common.ts_code import to_ts_code
from scripts.common.universe import load_quarantine_codes, load_universe_codes, members_tradable

OK_PREDICATE_VERSION = "v1.1"

# 初阈（可后收紧）
BAR_COVERAGE_MIN = 0.90
COMPUTABLE_COVERAGE_MIN = 0.50
LIMIT_COVERAGE_ASOF_MIN = 0.80
MAPPED_SYNC_MIN = 0.90

# metrics §3.3：RS / 温度初值
DEFAULT_MIN_HISTORY = 252

_OHLC_COLS = (
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "open_raw",
    "high_raw",
    "low_raw",
    "close_raw",
)


@dataclass
class CoverageMetrics:
    bar_coverage: float
    computable_coverage: float
    limit_coverage_asof: float
    open_raw_coverage_asof: float = 0.0  # 监控别名；判定以 bar_coverage 为准
    tradable_count: int = 0
    universe_size: int = 0
    mapped_size: int = 0
    mapped_sync_coverage: float = 0.0


@dataclass
class OkDecision:
    ok: bool
    status: str  # ok | partial | fail
    reason: str
    apply_limit_gate: bool


def evaluate_ok(
    trade_date: date,
    session_asof: date,
    metrics: CoverageMetrics,
    *,
    fatal: bool = False,
    computable_min: float = COMPUTABLE_COVERAGE_MIN,
) -> OkDecision:
    """D < session_asof：不卡 limit；D == asof：卡 limit_coverage_asof。"""
    if fatal:
        return OkDecision(False, "fail", "fatal_error", trade_date == session_asof)

    if trade_date > session_asof:
        return OkDecision(False, "fail", "trade_date_after_asof", False)

    apply_limit = trade_date == session_asof

    if metrics.mapped_sync_coverage < MAPPED_SYNC_MIN:
        return OkDecision(
            False,
            "partial",
            "mapped_sync_coverage<%.2f" % MAPPED_SYNC_MIN,
            apply_limit,
        )
    if metrics.bar_coverage < BAR_COVERAGE_MIN:
        return OkDecision(
            False, "partial", "bar_coverage<%.2f" % BAR_COVERAGE_MIN, apply_limit
        )
    if metrics.computable_coverage < computable_min:
        return OkDecision(
            False,
            "partial",
            "computable_coverage<%.2f" % computable_min,
            apply_limit,
        )
    if apply_limit and metrics.limit_coverage_asof < LIMIT_COVERAGE_ASOF_MIN:
        return OkDecision(
            False,
            "partial",
            "limit_coverage_asof<%.2f" % LIMIT_COVERAGE_ASOF_MIN,
            True,
        )
    return OkDecision(True, "ok", "passed", apply_limit)


def _ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return float(num) / float(den)


def _has_full_ohlc(row: tuple) -> bool:
    return all(v is not None for v in row)


def compute_coverage_from_bars(
    conn: sqlite3.Connection,
    trade_date: date,
    *,
    universe: Optional[Sequence[str]] = None,
    quarantine: Optional[Sequence[str]] = None,
    min_history: Optional[int] = None,
) -> CoverageMetrics:
    """对 U=members_tradable 统计 bar / computable / limit 覆盖率。"""
    if min_history is None:
        min_history = DEFAULT_MIN_HISTORY
    td = trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
    uni = [to_ts_code(c) for c in (universe if universe is not None else load_universe_codes())]
    qua = {to_ts_code(c) for c in (quarantine if quarantine is not None else load_quarantine_codes())}
    mapped = [c for c in uni if c not in qua]
    mapped_size = len(mapped)
    synced = 0
    for ts in mapped:
        row = conn.execute(
            """
            SELECT flag_source FROM bars WHERE ts_code=? AND trade_date=?
            """,
            (ts, td),
        ).fetchone()
        if row is not None and row[0]:
            synced += 1
    mapped_sync = _ratio(synced, mapped_size)

    U = members_tradable(conn, trade_date, universe=uni, quarantine=qua)
    n = len(U)
    if n == 0:
        return CoverageMetrics(
            bar_coverage=0.0,
            computable_coverage=0.0,
            limit_coverage_asof=0.0,
            open_raw_coverage_asof=0.0,
            tradable_count=0,
            universe_size=0,
            mapped_size=mapped_size,
            mapped_sync_coverage=mapped_sync,
        )

    bar_ok = 0
    open_raw_ok = 0
    limit_ok = 0
    computable_ok = 0
    cols = ", ".join(_OHLC_COLS)
    for ts in U:
        row = conn.execute(
            """
            SELECT %s, open_raw, limit_up, limit_down, flag_source
            FROM bars WHERE ts_code=? AND trade_date=?
            """
            % cols,
            (ts, td),
        ).fetchone()
        if row is None:
            continue
        ohlc = row[:8]
        open_raw = row[8]
        limit_up, limit_down, flag_source = row[9], row[10], row[11]
        if _has_full_ohlc(ohlc) and flag_source:
            bar_ok += 1
        if open_raw is not None:
            open_raw_ok += 1
        if limit_up is not None and limit_down is not None:
            limit_ok += 1
        hist = conn.execute(
            """
            SELECT COUNT(*) FROM bars
            WHERE ts_code=? AND trade_date<=? AND close_qfq IS NOT NULL
            """,
            (ts, td),
        ).fetchone()[0]
        if hist >= min_history:
            computable_ok += 1

    return CoverageMetrics(
        bar_coverage=_ratio(bar_ok, n),
        computable_coverage=_ratio(computable_ok, n),
        limit_coverage_asof=_ratio(limit_ok, n),
        open_raw_coverage_asof=_ratio(open_raw_ok, n),
        tradable_count=n,
        universe_size=n,
        mapped_size=mapped_size,
        mapped_sync_coverage=mapped_sync,
    )
