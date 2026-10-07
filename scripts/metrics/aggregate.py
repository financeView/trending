"""L2/L1 basket helpers (closure, weights, taxonomy).

Universe may be a stub map. Weights: float_mv null→1.0 then normalize.
L1 members = member closure once (union of mapped L2 stocks), not nested L2 series.

Production L1 same-engine (synth OHLC → shared FSM) lives in ``daily_run``.
``aggregate_l1`` remains for legacy tests; it is not the ``daily_l1`` write path.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from scripts.metrics.hysteresis import inv_rank
from scripts.metrics.temp_raw import RANK
from scripts.common.universe import l1_to_l2_map, l2_members_map, load_l2_to_l1, load_stock_sw_l2

MEMBER_SET = "tradable"

_TAX_BY_TS: Optional[Dict[str, tuple]] = None


def _taxonomy_index() -> Dict[str, tuple]:
    global _TAX_BY_TS
    if _TAX_BY_TS is None:
        l1_of = {r["code"]: r["l1_id"] for r in load_l2_to_l1()}
        idx: Dict[str, tuple] = {}
        for row in load_stock_sw_l2():
            code = row["sw_l2_code"]
            if not code:
                continue
            idx[row["ts_code"]] = (code, l1_of.get(code))
        _TAX_BY_TS = idx
    return _TAX_BY_TS


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
    mapping = l2_members if l2_members is not None else l2_members_map()
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
    """Return (sw_l2_code, l1_id) from the YAML map, or (None, None)."""
    if l2_members is None and l1_to_l2 is None:
        return _taxonomy_index().get(ts_code, (None, None))
    mapping = l2_members if l2_members is not None else l2_members_map()
    buckets = l1_to_l2 if l1_to_l2 is not None else l1_to_l2_map()
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
    buckets = l1_to_l2 if l1_to_l2 is not None else l1_to_l2_map()
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
    mapping = l2_members if l2_members is not None else l2_members_map()
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
