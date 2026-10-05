"""Load `config/eval/costs.yaml` (backtest-eval §4.3)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = _ROOT / "config" / "eval" / "costs.yaml"


@dataclass(frozen=True)
class EvalCosts:
    cost_version: str
    commission_rate: float
    min_commission: float
    stamp_tax_sell: float
    impact_bp_buy: float
    impact_bp_sell: float
    lot_size: int
    N_cap: int
    initial_cash: float
    limit_rule: str
    fill_price: str
    hs300_series: str


def load_costs(path: Optional[str | Path] = None) -> EvalCosts:
    p = Path(path) if path else _DEFAULT
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return EvalCosts(
        cost_version=str(data["cost_version"]),
        commission_rate=float(data["commission_rate"]),
        min_commission=float(data.get("min_commission") or 0),
        stamp_tax_sell=float(data["stamp_tax_sell"]),
        impact_bp_buy=float(data["impact_bp_buy"]),
        impact_bp_sell=float(data["impact_bp_sell"]),
        lot_size=int(data["lot_size"]),
        N_cap=int(data["N_cap"]),
        initial_cash=float(data["initial_cash"]),
        limit_rule=str(data.get("limit_rule") or "vendor_fields"),
        fill_price=str(data.get("fill_price") or "open_raw"),
        hs300_series=str(data.get("hs300_series") or "000300.SH"),
    )


def buy_px(open_raw: float, costs: EvalCosts) -> float:
    return float(open_raw) * (1.0 + costs.impact_bp_buy / 10000.0)


def sell_px(open_raw: float, costs: EvalCosts) -> float:
    return float(open_raw) * (1.0 - costs.impact_bp_sell / 10000.0)


def trade_costs(qty: float, px: float, side: str, costs: EvalCosts) -> float:
    notional = abs(qty) * px
    comm = max(notional * costs.commission_rate, costs.min_commission)
    stamp = notional * costs.stamp_tax_sell if side == "sell" else 0.0
    return comm + stamp
