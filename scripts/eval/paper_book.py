#!/usr/bin/env python3
"""Audit/synthetic H: walk trade days through fill_day. Does not write paper_fill."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common.bars import DEFAULT_BARS_DB, load_ohlc_limits
from scripts.common.calendar import prev_trade_date, trading_days_inclusive
from scripts.eval.book import BookState
from scripts.eval.costs import EvalCosts, load_costs
from scripts.eval.fill_day import fill_day


def pair_rounds(fills: Iterable[Mapping[str, Any]]) -> List[dict]:
    """FIFO open/close per ts_code using fill order (not first ticker buy)."""
    open_buys: Dict[str, List[Mapping[str, Any]]] = {}
    rounds: List[dict] = []
    for row in fills:
        if row.get("status") != "filled":
            continue
        ts = str(row.get("ts_code") or "")
        if row.get("side") == "buy":
            open_buys.setdefault(ts, []).append(row)
        elif row.get("side") == "sell":
            stack = open_buys.get(ts) or []
            if not stack:
                continue
            buy = stack.pop(0)
            rounds.append({"buy": buy, "sell": row})
    return rounds


def window_kpis(fills: Iterable[Mapping[str, Any]], book: BookState) -> dict:
    rows = list(fills)
    rounds = pair_rounds(rows)
    n_closed = len(rounds)
    n_open_end = len(book.positions)
    n_fills = len(rows)
    if n_closed == 0:
        return {"n_open_end": n_open_end, "n_closed": 0, "win_rate": None, "n_fills": n_fills}
    wins = 0
    for rnd in rounds:
        buy_px = rnd["buy"].get("px")
        sell_px = rnd["sell"].get("px")
        if buy_px is None or sell_px is None:
            continue
        if float(sell_px) > float(buy_px):
            wins += 1
    return {
        "n_open_end": n_open_end,
        "n_closed": n_closed,
        "win_rate": wins / n_closed,
        "n_fills": n_fills,
    }


def _index_signals(signals: Iterable[Mapping[str, Any]]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for raw in signals:
        s = dict(raw)
        day = str(s.get("trade_date") or "")
        out.setdefault(day, []).append(s)
    return out


def replay_window(
    start: date,
    end: date,
    *,
    signals: Iterable[Mapping[str, Any]],
    bars_by_day: Mapping[str, Mapping[str, Mapping[str, Any]]],
    costs: EvalCosts,
    book: Optional[BookState] = None,
    run_id: str = "audit-h",
) -> dict:
    if book is None:
        book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    by_day = _index_signals(signals)
    all_fills: List[dict] = []
    for T in trading_days_inclusive(start, end):
        prev = prev_trade_date(T)
        sigs = by_day.get(prev.isoformat() if prev else "", [])
        bars = bars_by_day.get(T.isoformat()) or {}
        fills = fill_day(
            T.isoformat(),
            sigs,
            book,
            bars,
            costs,
            track="H",
            run_id=run_id,
        )
        all_fills.extend(fills)
    kpi = window_kpis(all_fills, book)
    return {"fills": all_fills, "kpi": kpi, "book": book}


def _write_out(out_dir: str, run_id: str, payload: dict) -> None:
    dest = os.path.join(out_dir, run_id)
    os.makedirs(dest, exist_ok=True)
    fills = payload["fills"]
    kpi = payload["kpi"]
    with open(os.path.join(dest, "fills.json"), "w", encoding="utf-8") as f:
        json.dump(fills, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(dest, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(kpi, f, ensure_ascii=False, indent=2)


def _codes_from_signals(signals: List[Mapping[str, Any]]) -> List[str]:
    return sorted({str(s.get("ts_code")) for s in signals if s.get("ts_code")})


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Audit H fill_day window (does not write paper_fill)")
    p.add_argument("--from", dest="date_from", required=True)
    p.add_argument("--to", dest="date_to", required=True)
    p.add_argument("--signals-json", default="", help="in-memory/file events; not trend.db paper_fill")
    p.add_argument("--bars-db", default="")
    p.add_argument("--out", default="", help="write output/eval/{run_id}/ JSON")
    p.add_argument("--run-id", default="audit-h")
    args = p.parse_args(argv)
    start = date.fromisoformat(args.date_from)
    end = date.fromisoformat(args.date_to)
    signals: List[dict] = []
    if args.signals_json:
        signals = json.loads(open(args.signals_json, encoding="utf-8").read())
    costs = load_costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    bars_by_day: Dict[str, dict] = {}
    bars_path = args.bars_db or DEFAULT_BARS_DB
    codes = _codes_from_signals(signals)
    for T in trading_days_inclusive(start, end):
        bars_by_day[T.isoformat()] = load_ohlc_limits(bars_path, T.isoformat(), codes)
    result = replay_window(
        start,
        end,
        signals=signals,
        bars_by_day=bars_by_day,
        costs=costs,
        book=book,
        run_id=args.run_id,
    )
    print(
        "[paper_book] from=%s to=%s n_fills=%s n_closed=%s n_open_end=%s win_rate=%s"
        % (
            args.date_from,
            args.date_to,
            result["kpi"].get("n_fills"),
            result["kpi"]["n_closed"],
            result["kpi"]["n_open_end"],
            result["kpi"]["win_rate"],
        )
    )
    if args.out:
        _write_out(args.out, args.run_id, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
