"""Pure L2 OHLC synthesis via float_mv-weighted chain returns + HL-ratio proxy."""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from scripts.metrics.aggregate import normalize_weights


def _iso(d: date) -> str:
    return d.isoformat()


def _finite_pos(x: Any) -> bool:
    if x is None:
        return False
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and v > 0


def _finite(x: Any) -> bool:
    if x is None:
        return False
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v)


def _flag_zero(x: Any) -> bool:
    """True when flag is absent/0/false (eligible); ST/suspended when truthy/nonzero."""
    if x is None:
        return True
    try:
        return int(x) == 0
    except (TypeError, ValueError):
        return not bool(x)


def _ohlc_field(bar: Mapping[str, Any], primary: str, fallback: str) -> Any:
    if primary in bar and bar[primary] is not None:
        return bar[primary]
    return bar.get(fallback)


def _index_bars(
    member_bars_by_ts: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    idx: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for ts_code, rows in member_bars_by_ts.items():
        for row in rows:
            td = row.get("trade_date")
            if td is None:
                continue
            if isinstance(td, date):
                key = _iso(td)
            else:
                key = str(td)[:10]
            idx[(ts_code, key)] = row
    return idx


def synthesize_l2_bars(
    member_bars_by_ts: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    trade_dates: Sequence[date],
) -> list[dict]:
    """Return OHLC records for replay_from_ohlc (skipped days omitted).

    Each record: trade_date, close_qfq, high_qfq, low_qfq, is_st=0, is_suspended=0.
    Prev day = previous element in injected trade_dates (full calendar).
    """
    bars = _index_bars(member_bars_by_ts)
    ts_codes = list(member_bars_by_ts.keys())
    out: List[dict] = []
    p_prev: Optional[float] = None

    for i, t in enumerate(trade_dates):
        t_iso = _iso(t)
        prev_iso = _iso(trade_dates[i - 1]) if i > 0 else None

        # Membership: bar that day, close finite >0, not ST/suspended
        members: List[str] = []
        for ts in ts_codes:
            row = bars.get((ts, t_iso))
            if row is None:
                continue
            if not _finite_pos(row.get("close_qfq")):
                continue
            if not _flag_zero(row.get("is_st")):
                continue
            if not _flag_zero(row.get("is_suspended")):
                continue
            members.append(ts)

        # R_t: members with calendar prev close finite >0
        r_members: List[str] = []
        if prev_iso is not None:
            for ts in members:
                prev_row = bars.get((ts, prev_iso))
                if prev_row is not None and _finite_pos(prev_row.get("close_qfq")):
                    r_members.append(ts)

        if not r_members:
            # omit day; do not reset P_prev
            continue

        float_mvs = [bars[(ts, t_iso)].get("float_mv") for ts in r_members]
        weights = normalize_weights(float_mvs)
        r_t = 0.0
        for ts, w in zip(r_members, weights):
            c_t = float(bars[(ts, t_iso)]["close_qfq"])
            c_prev = float(bars[(ts, prev_iso)]["close_qfq"])
            r_t += w * (c_t / c_prev - 1.0)

        p_t = (1.0 + r_t) if p_prev is None else p_prev * (1.0 + r_t)
        if not math.isfinite(p_t):
            continue

        # M^H_t: members with high/low/close finite and close>0
        mh_members: List[str] = []
        for ts in members:
            row = bars[(ts, t_iso)]
            h = _ohlc_field(row, "high_qfq", "high")
            lo = _ohlc_field(row, "low_qfq", "low")
            c = row.get("close_qfq")
            if _finite(h) and _finite(lo) and _finite_pos(c):
                mh_members.append(ts)

        if mh_members:
            mh_mvs = [bars[(ts, t_iso)].get("float_mv") for ts in mh_members]
            mh_w = normalize_weights(mh_mvs)
            bar_h = 0.0
            bar_l = 0.0
            for ts, w in zip(mh_members, mh_w):
                row = bars[(ts, t_iso)]
                c = float(row["close_qfq"])
                h = float(_ohlc_field(row, "high_qfq", "high"))
                lo = float(_ohlc_field(row, "low_qfq", "low"))
                bar_h += w * (h / c)
                bar_l += w * (lo / c)
            high_t = p_t * bar_h
            low_t = p_t * bar_l
        else:
            high_t = p_t
            low_t = p_t

        # Clamp
        low_t = min(low_t, p_t, high_t)
        high_t = max(low_t, p_t, high_t)
        if not (_finite_pos(low_t) and _finite_pos(p_t) and _finite_pos(high_t)):
            continue

        out.append(
            {
                "trade_date": t_iso,
                "close_qfq": p_t,
                "high_qfq": high_t,
                "low_qfq": low_t,
                "is_st": 0,
                "is_suspended": 0,
            }
        )
        p_prev = p_t

    return out
