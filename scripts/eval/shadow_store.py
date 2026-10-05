"""Serialize BookState for the single L shadow instance (trend.db)."""
from __future__ import annotations

import json

from scripts.eval.book import BookState, PendingSell, Position
from scripts.eval.costs import EvalCosts


def book_to_dict(book: BookState) -> dict:
    return {
        "cash": book.cash,
        "last_equity": book.last_equity,
        "positions": {
            ts: {
                "shares": p.shares,
                "entry_date": p.entry_date,
                "entry_px": p.entry_px,
                "signal_date": p.signal_date,
                "signal_event_id": p.signal_event_id,
                "exit_kind": p.exit_kind,
            }
            for ts, p in book.positions.items()
        },
        "pending_sells": [
            {
                "ts_code": s.ts_code,
                "signal_date": s.signal_date,
                "signal_event_id": s.signal_event_id,
                "exit_kind": s.exit_kind,
            }
            for s in book.pending_sells
        ],
    }


def book_from_dict(data: dict, *, initial_cash: float) -> BookState:
    if not data:
        return BookState(cash=initial_cash, last_equity=initial_cash)
    pos = {}
    for ts, p in (data.get("positions") or {}).items():
        pos[ts] = Position(
            shares=int(p["shares"]),
            entry_date=str(p["entry_date"]),
            entry_px=float(p["entry_px"]),
            signal_date=str(p["signal_date"]),
            signal_event_id=p.get("signal_event_id"),
            exit_kind=p.get("exit_kind"),
        )
    pending = [
        PendingSell(
            ts_code=str(s["ts_code"]),
            signal_date=str(s["signal_date"]),
            signal_event_id=s.get("signal_event_id"),
            exit_kind=s.get("exit_kind"),
        )
        for s in (data.get("pending_sells") or [])
    ]
    return BookState(
        cash=float(data.get("cash", initial_cash)),
        last_equity=float(data.get("last_equity", initial_cash)),
        positions=pos,
        pending_sells=pending,
    )


def load_shadow_book(conn, costs: EvalCosts) -> BookState:
    row = conn.execute("SELECT payload FROM shadow_book_state WHERE id=1").fetchone()
    if not row:
        return BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    data = json.loads(row[0])
    return book_from_dict(data, initial_cash=costs.initial_cash)


def save_shadow_book(conn, book: BookState, commit: bool = True) -> None:
    payload = json.dumps(book_to_dict(book), ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO shadow_book_state (id, payload) VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
        """,
        (payload,),
    )
    if commit:
        conn.commit()
