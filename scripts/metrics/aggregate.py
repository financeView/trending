"""L2/L1 synthetic baskets (metrics §10 MVP).

Universe may be a stub map. Weights: float_mv null→1.0 then normalize.
L1 = member closure once (union of mapped L2 stocks), not nested L2 series.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from scripts.metrics.hysteresis import inv_rank
from scripts.metrics.temp_raw import RANK

MEMBER_SET = "tradable"

# Stub SW L2 → stocks until full taxonomy YAML lands.
STUB_L2_MEMBERS: Dict[str, List[str]] = {
    "801780": ["000001.SZ", "600000.SH", "601318.SH"],
    "801180": ["000002.SZ"],
    "801120": ["600519.SH"],
}

# L1 → L2 codes; members = union of those L2 lists (closure once).
STUB_L1_TO_L2: Dict[str, List[str]] = {
    "l1_finance": ["801780"],
    "l1_property_infra": ["801180"],
    "l1_staples": ["801120"],
}


def weight_raw(float_mv: Optional[float]) -> float:
    """market-data §6.3: missing/non-positive mv → 1.0, not whole-basket equal weight."""
    if float_mv is None:
        return 1.0
    try:
        v = float(float_mv)
    except (TypeError, ValueError):
        return 1.0
    if v <= 0 or v != v:  # NaN
        return 1.0
    return v


def normalize_weights(float_mvs: Sequence[Optional[float]]) -> List[float]:
    raws = [weight_raw(x) for x in float_mvs]
    total = sum(raws)
    if total <= 0:
        n = len(raws)
        return [1.0 / n] * n if n else []
    return [r / total for r in raws]


def member_closure(
    l2_codes: Sequence[str],
    l2_members: Mapping[str, Sequence[str]] | None = None,
) -> List[str]:
    """L1 members = ∪ stocks of mapped L2 (no nested L2 aggregation)."""
    mapping = l2_members if l2_members is not None else STUB_L2_MEMBERS
    seen: List[str] = []
    have = set()
    for l2 in l2_codes:
        for ts in mapping.get(l2, ()):
            if ts not in have:
                have.add(ts)
                seen.append(ts)
    return seen


def taxonomy_for_stock(
    ts_code: str,
    *,
    l2_members: Mapping[str, Sequence[str]] | None = None,
    l1_to_l2: Mapping[str, Sequence[str]] | None = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return (sw_l2_code, l1_id) from the stub map, or (None, None)."""
    mapping = l2_members if l2_members is not None else STUB_L2_MEMBERS
    buckets = l1_to_l2 if l1_to_l2 is not None else STUB_L1_TO_L2
    sw = None
    for l2, members in mapping.items():
        if ts_code in members:
            sw = l2
            break
    if sw is None:
        return None, None
    for l1, l2s in buckets.items():
        if sw in l2s:
            return sw, l1
    return sw, None


def stub_l1_members(
    l1_to_l2: Mapping[str, Sequence[str]] | None = None,
    l2_members: Mapping[str, Sequence[str]] | None = None,
) -> Dict[str, List[str]]:
    buckets = l1_to_l2 if l1_to_l2 is not None else STUB_L1_TO_L2
    return {l1: member_closure(l2s, l2_members) for l1, l2s in buckets.items()}


def _index_by_code(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    out: Dict[str, Mapping[str, Any]] = {}
    for r in rows:
        code = r.get("ts_code") or r.get("code")
        if code:
            out[str(code)] = r
    return out


def _weighted_mean(values: Sequence[Optional[float]], weights: Sequence[float]) -> Optional[float]:
    num = 0.0
    den = 0.0
    any_v = False
    for v, w in zip(values, weights):
        if v is None:
            continue
        any_v = True
        num += float(v) * w
        den += w
    if not any_v or den <= 0:
        return None
    return num / den


def _majority_t(temps: Sequence[Optional[str]], weights: Sequence[float]) -> Optional[str]:
    acc: Dict[int, float] = defaultdict(float)
    for t, w in zip(temps, weights):
        if t is None or t not in RANK:
            continue
        acc[RANK[t]] += w
    if not acc:
        return None
    best = max(acc.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return inv_rank(best)


def aggregate_members(
    stock_rows: Sequence[Mapping[str, Any]],
    members: Sequence[str],
    *,
    trade_date: str,
    code: str,
    member_set: str = MEMBER_SET,
) -> Dict[str, Any]:
    """One basket row from tradable member stocks. Does not write stage_score."""
    del member_set  # documented contract; caller filters tradable before passing rows
    by_code = _index_by_code(stock_rows)
    present = [m for m in members if m in by_code]
    members_total = len(members)
    members_tradable = len(present)
    if not present:
        return {
            "trade_date": trade_date,
            "code": code,
            "T": None,
            "S_temp": None,
            "RS": None,
            "right_side": None,
            "tag_warm_to_hot": 0,
            "tag_warm_to_flat": 0,
            "solar_term": None,
            "members_tradable": 0,
            "members_total": members_total,
        }
    rows = [by_code[m] for m in present]
    weights = normalize_weights([r.get("float_mv") for r in rows])
    t = _majority_t([r.get("T") for r in rows], weights)
    s_temp = _weighted_mean([r.get("S_temp") for r in rows], weights)
    rs = _weighted_mean([r.get("RS") for r in rows], weights)
    rs_w = _weighted_mean(
        [None if r.get("right_side") is None else float(int(bool(r.get("right_side")))) for r in rows],
        weights,
    )
    right_side = None if rs_w is None else int(rs_w >= 0.5)
    tag_hot = int(any(bool(r.get("tag_warm_to_hot")) for r in rows))
    tag_flat = int(any(bool(r.get("tag_warm_to_flat")) for r in rows))
    # solar_term: highest-weight member that has a term
    solar = None
    best_w = -1.0
    for r, w in zip(rows, weights):
        term = r.get("solar_term")
        if term and w >= best_w:
            solar = term
            best_w = w
    return {
        "trade_date": trade_date,
        "code": code,
        "T": t,
        "S_temp": s_temp,
        "RS": rs,
        "right_side": right_side,
        "tag_warm_to_hot": tag_hot,
        "tag_warm_to_flat": tag_flat,
        "solar_term": solar,
        "members_tradable": members_tradable,
        "members_total": members_total,
    }


def aggregate_l2(
    stock_rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    *,
    l2_members: Mapping[str, Sequence[str]] | None = None,
) -> List[Dict[str, Any]]:
    mapping = l2_members if l2_members is not None else STUB_L2_MEMBERS
    return [
        aggregate_members(stock_rows, members, trade_date=trade_date, code=code)
        for code, members in mapping.items()
    ]


def aggregate_l1(
    stock_rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    *,
    l1_to_l2: Mapping[str, Sequence[str]] | None = None,
    l2_members: Mapping[str, Sequence[str]] | None = None,
) -> List[Dict[str, Any]]:
    groups = stub_l1_members(l1_to_l2, l2_members)
    return [
        aggregate_members(stock_rows, members, trade_date=trade_date, code=code)
        for code, members in groups.items()
    ]
