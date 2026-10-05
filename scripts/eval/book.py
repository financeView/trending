"""In-memory book for fill_day (backtest-eval §4.5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


@dataclass
class Position:
    shares: int
    entry_date: str
    entry_px: float
    signal_date: str
    signal_event_id: Optional[int] = None
    exit_kind: Optional[str] = None


@dataclass
class PendingSell:
    ts_code: str
    signal_date: str
    signal_event_id: Optional[int]
    exit_kind: Optional[str]


@dataclass
class BookState:
    cash: float
    last_equity: float
    positions: Dict[str, Position] = field(default_factory=dict)
    pending_sells: List[PendingSell] = field(default_factory=list)

    def mtm(self, close_raw: Dict[str, float]) -> float:
        gross = 0.0
        for ts, pos in self.positions.items():
            px = close_raw.get(ts)
            if px is None:
                px = pos.entry_px
            gross += pos.shares * float(px)
        self.last_equity = self.cash + gross
        return self.last_equity
