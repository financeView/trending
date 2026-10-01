"""market-data-contract §7.2 ok 谓词。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


OK_PREDICATE_VERSION = "v1"

# 初阈（可后收紧）
BAR_COVERAGE_MIN = 0.90
COMPUTABLE_COVERAGE_MIN = 0.50
LIMIT_COVERAGE_ASOF_MIN = 0.80


@dataclass
class CoverageMetrics:
    bar_coverage: float
    computable_coverage: float
    limit_coverage_asof: float
    open_raw_coverage_asof: float = 0.0  # 监控别名；判定以 bar_coverage 为准
    tradable_count: int = 0
    universe_size: int = 0


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
