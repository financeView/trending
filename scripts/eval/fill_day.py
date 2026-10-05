"""Shared fill_day (backtest-eval §4.4–4.6)."""
from __future__ import annotations

import json
import math
import uuid
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from scripts.common.calendar import next_trade_date
from scripts.eval.book import BookState, PendingSell, Position
from scripts.eval.costs import EvalCosts, buy_px, sell_px, trade_costs

TERMINAL = frozenset(
    {
        "filled",
        "unfilled_buy",
        "unfilled_sell",
        "rejected_no_slot",
        "rejected_no_cash",
        "rejected_lot",
        "ignored_already_held",
        "ignored_flat_exit",
        "data_gap",
    }
)


def _d(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _intent_date(signal_date: str, fill_date: str) -> str:
    if not signal_date:
        return fill_date
    try:
        nxt = next_trade_date(date.fromisoformat(str(signal_date)[:10]))
    except (TypeError, ValueError, RuntimeError):
        return fill_date
    if nxt is None:
        return fill_date
    return nxt.isoformat()


def _sig_detail(sig: Mapping[str, Any]) -> dict:
    detail = sig.get("detail") or {}
    if isinstance(detail, str):
        if not detail:
            return {}
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(detail, dict):
        return detail
    return {}


def _bar(bars: Mapping[str, Mapping[str, Any]], ts: str) -> Optional[Mapping[str, Any]]:
    return bars.get(ts)


def _open_raw(bar: Mapping[str, Any]) -> Optional[float]:
    v = bar.get("open_raw")
    if v is None:
        return None
    return float(v)


def _limits(bar: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    up, down = bar.get("limit_up"), bar.get("limit_down")
    if up is None or down is None:
        return None, None
    return float(up), float(down)


def _suspended(bar: Mapping[str, Any]) -> bool:
    return bool(int(bar.get("is_suspended") or 0))


def _fill_row(
    *,
    track: str,
    side: str,
    ts_code: str,
    fill_date: str,
    signal_date: str,
    signal_event_id: Optional[int],
    status: str,
    qty: float = 0.0,
    px: Optional[float] = None,
    costs: float = 0.0,
    exit_kind: Optional[str] = None,
    reject_reason: Optional[str] = None,
    cost_version: str,
    param_version: Optional[str],
    map_version: Optional[str],
    run_id: str,
) -> dict:
    return {
        "fill_id": str(uuid.uuid4()),
        "track": track,
        "rule_id": "mvp_right_side_v1",
        "cost_version": cost_version,
        "param_version": param_version,
        "map_version": map_version,
        "signal_event_id": signal_event_id,
        "signal_date": signal_date,
        "intent_date": _intent_date(signal_date, fill_date),
        "fill_date": fill_date,
        "ts_code": ts_code,
        "side": side,
        "exit_kind": exit_kind,
        "qty": qty,
        "px": px,
        "costs": costs,
        "status": status,
        "reject_reason": reject_reason,
        "run_id": run_id,
    }


def fill_day(
    T: date | str,
    signals_prev: Iterable[Mapping[str, Any]],
    book: BookState,
    bars_T: Mapping[str, Mapping[str, Any]],
    costs: EvalCosts,
    *,
    track: str = "H",
    param_version: Optional[str] = None,
    map_version: Optional[str] = None,
    run_id: str = "test",
    limit_up_unfillable: bool = False,
    skip_event_days: Optional[set] = None,
) -> List[dict]:
    """One trade day: pending sells → EXIT sells → ENTER buys → MTM.

    ``signals_prev`` are events whose confirmation date is prev_trade_date(T).
    ``skip_event_days`` is {(signal_event_id, side, fill_date)} already persisted for T.
    """
    td = _d(T)
    fills: List[dict] = []
    equity_ex_open = book.last_equity
    signals = list(signals_prev)
    blocked = skip_event_days or set()

    def _blocked(sid: Optional[int], side: str) -> bool:
        if sid is None:
            return False
        return (int(sid), side, td) in blocked

    def emit(**kw) -> dict:
        row = _fill_row(
            track=track,
            fill_date=td,
            cost_version=costs.cost_version,
            param_version=param_version,
            map_version=map_version,
            run_id=run_id,
            **kw,
        )
        fills.append(row)
        return row

    def try_sell(ts: str, *, signal_date: str, sid: Optional[int], exit_kind: Optional[str]) -> str:
        if _blocked(sid, "sell"):
            return "skipped"
        bar = _bar(bars_T, ts)
        if bar is None or _open_raw(bar) is None:
            emit(
                side="sell",
                ts_code=ts,
                signal_date=signal_date,
                signal_event_id=sid,
                status="data_gap",
                exit_kind=exit_kind,
                reject_reason="missing_open_raw",
            )
            return "data_gap"
        up, down = _limits(bar)
        if up is None or down is None:
            emit(
                side="sell",
                ts_code=ts,
                signal_date=signal_date,
                signal_event_id=sid,
                status="data_gap",
                exit_kind=exit_kind,
                reject_reason="missing_limits",
            )
            return "data_gap"
        o = _open_raw(bar)
        assert o is not None
        if _suspended(bar):
            emit(
                side="sell",
                ts_code=ts,
                signal_date=signal_date,
                signal_event_id=sid,
                status="unfilled_sell",
                exit_kind=exit_kind,
                reject_reason="suspended",
            )
            return "unfilled_sell"
        if o <= down:
            emit(
                side="sell",
                ts_code=ts,
                signal_date=signal_date,
                signal_event_id=sid,
                status="unfilled_sell",
                exit_kind=exit_kind,
                reject_reason="limit_down",
            )
            return "unfilled_sell"
        if limit_up_unfillable and o >= up:
            emit(
                side="sell",
                ts_code=ts,
                signal_date=signal_date,
                signal_event_id=sid,
                status="unfilled_sell",
                exit_kind=exit_kind,
                reject_reason="limit_up",
            )
            return "unfilled_sell"
        pos = book.positions.get(ts)
        if pos is None:
            emit(
                side="sell",
                ts_code=ts,
                signal_date=signal_date,
                signal_event_id=sid,
                status="ignored_flat_exit",
                exit_kind=exit_kind,
            )
            return "ignored_flat_exit"
        px = sell_px(o, costs)
        qty = float(pos.shares)
        fee = trade_costs(qty, px, "sell", costs)
        book.cash += qty * px - fee
        del book.positions[ts]
        emit(
            side="sell",
            ts_code=ts,
            signal_date=signal_date,
            signal_event_id=sid,
            status="filled",
            qty=qty,
            px=px,
            costs=fee,
            exit_kind=exit_kind,
        )
        return "filled"

    # 1) pending sells
    still_pending: List[PendingSell] = []
    for pend in list(book.pending_sells):
        st = try_sell(
            pend.ts_code,
            signal_date=pend.signal_date,
            sid=pend.signal_event_id,
            exit_kind=pend.exit_kind,
        )
        if st in ("unfilled_sell", "skipped"):
            still_pending.append(pend)
    book.pending_sells = still_pending

    exits = [s for s in signals if s.get("event") == "EXIT_RIGHT"]
    enters = [s for s in signals if s.get("event") == "ENTER_RIGHT"]

    # 2) due EXIT sells
    for sig in exits:
        ts = str(sig.get("ts_code"))
        sid = sig.get("id")
        sid_i = None if sid is None else int(sid)
        exit_kind = _sig_detail(sig).get("exit_kind")
        if _blocked(sid_i, "sell"):
            continue
        if ts not in book.positions:
            emit(
                side="sell",
                ts_code=ts,
                signal_date=str(sig.get("trade_date") or ""),
                signal_event_id=sid_i,
                status="ignored_flat_exit",
                exit_kind=exit_kind,
            )
            continue
        st = try_sell(
            ts,
            signal_date=str(sig.get("trade_date") or ""),
            sid=sid_i,
            exit_kind=exit_kind,
        )
        if st == "unfilled_sell":
            book.pending_sells.append(
                PendingSell(
                    ts_code=ts,
                    signal_date=str(sig.get("trade_date") or ""),
                    signal_event_id=sid_i,
                    exit_kind=exit_kind,
                )
            )

    # 3) ENTER buys
    def _rs(sig: Mapping[str, Any]) -> float:
        v = sig.get("RS")
        if v is None:
            return float("-inf")
        return float(v)

    enters_sorted = sorted(enters, key=lambda s: (-_rs(s), str(s.get("ts_code"))))
    for sig in enters_sorted:
        ts = str(sig.get("ts_code"))
        sid = None if sig.get("id") is None else int(sig["id"])
        sdate = str(sig.get("trade_date") or "")
        if _blocked(sid, "buy"):
            continue
        if ts in book.positions:
            emit(
                side="buy",
                ts_code=ts,
                signal_date=sdate,
                signal_event_id=sid,
                status="ignored_already_held",
            )
            continue
        bar = _bar(bars_T, ts)
        if bar is None or _open_raw(bar) is None:
            emit(
                side="buy",
                ts_code=ts,
                signal_date=sdate,
                signal_event_id=sid,
                status="data_gap",
                reject_reason="missing_open_raw",
            )
            continue
        up, down = _limits(bar)
        if up is None or down is None:
            emit(
                side="buy",
                ts_code=ts,
                signal_date=sdate,
                signal_event_id=sid,
                status="data_gap",
                reject_reason="missing_limits",
            )
            continue
        o = _open_raw(bar)
        assert o is not None
        if _suspended(bar) or o >= up:
            emit(
                side="buy",
                ts_code=ts,
                signal_date=sdate,
                signal_event_id=sid,
                status="unfilled_buy",
                reject_reason="suspended" if _suspended(bar) else "limit_up",
            )
            continue
        if len(book.positions) >= costs.N_cap:
            emit(
                side="buy",
                ts_code=ts,
                signal_date=sdate,
                signal_event_id=sid,
                status="rejected_no_slot",
            )
            continue
        px = buy_px(o, costs)
        target = equity_ex_open / float(costs.N_cap)
        lots = math.floor(target / px / costs.lot_size)
        qty = int(lots * costs.lot_size)
        if qty < costs.lot_size:
            emit(
                side="buy",
                ts_code=ts,
                signal_date=sdate,
                signal_event_id=sid,
                status="rejected_lot",
            )
            continue
        fee = trade_costs(qty, px, "buy", costs)
        need = qty * px + fee
        if need > book.cash + 1e-9:
            emit(
                side="buy",
                ts_code=ts,
                signal_date=sdate,
                signal_event_id=sid,
                status="rejected_no_cash",
            )
            continue
        book.cash -= need
        book.positions[ts] = Position(
            shares=qty,
            entry_date=td,
            entry_px=px,
            signal_date=sdate,
            signal_event_id=sid,
        )
        emit(
            side="buy",
            ts_code=ts,
            signal_date=sdate,
            signal_event_id=sid,
            status="filled",
            qty=float(qty),
            px=px,
            costs=fee,
        )

    close_map = {}
    for ts, bar in bars_T.items():
        if bar.get("close_raw") is not None:
            close_map[ts] = float(bar["close_raw"])
    book.mtm(close_map)
    return fills


def round_kpis(fills: List[dict], book: BookState) -> dict:
    """§4.7: win_rate only on closed filled-sell rounds; n_open_end = still held."""
    closed = [
        f for f in fills if f.get("status") == "filled" and f.get("side") == "sell"
    ]
    n_closed = len(closed)
    n_open_end = len(book.positions)
    if n_closed == 0:
        return {"n_open_end": n_open_end, "n_closed": 0, "win_rate": None}
    wins = 0
    for sell in closed:
        ts = sell.get("ts_code")
        buy = next(
            (
                f
                for f in fills
                if f.get("side") == "buy"
                and f.get("status") == "filled"
                and f.get("ts_code") == ts
            ),
            None,
        )
        if (
            buy
            and sell.get("px") is not None
            and buy.get("px") is not None
            and float(sell["px"]) > float(buy["px"])
        ):
            wins += 1
    return {
        "n_open_end": n_open_end,
        "n_closed": n_closed,
        "win_rate": wins / n_closed,
    }
