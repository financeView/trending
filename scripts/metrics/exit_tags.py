"""Pure exit-tag assignment (vol_expand / champagne / danger) — Spec §3.2."""
from __future__ import annotations

import json
import statistics
import sys
from typing import Any, List, Mapping, Optional, Sequence

from scripts.metrics.params import MetricsParams
from scripts.metrics.peer_rs import basket_peer_eligible, stock_peer_eligible
from scripts.metrics.percentile import scores_0_100

TAG_ORDER = ("vol_expand", "champagne", "danger")
TAG_DISPLAY = {
    "vol_expand": "波动率放大",
    "champagne": "开香槟",
    "danger": "危险信号",
}

_VOL_EXPAND_TERMS = frozenset({"小暑", "大暑"})


def format_tags_display(tags: Sequence[str]) -> str:
    present = set(tags)
    names = [TAG_DISPLAY[t] for t in TAG_ORDER if t in present]
    return "、".join(names)


def tags_to_sql(tags: Sequence[str]) -> str:
    present = set(tags)
    ordered = [t for t in TAG_ORDER if t in present]
    extras = [t for t in tags if t not in TAG_ORDER]
    return json.dumps(ordered + list(extras), ensure_ascii=False)


def _finite(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or abs(v) == float("inf"):
        return None
    return v


def daily_returns(closes: Sequence[Any]) -> List[Optional[float]]:
    """Spine daily returns: close_t / close_{t-1} - 1; index 0 always None."""
    out: List[Optional[float]] = [None] * len(closes)
    prev: Optional[float] = None
    for i, c in enumerate(closes):
        cur = _finite(c)
        if cur is None or prev is None or prev == 0.0:
            out[i] = None
        else:
            out[i] = cur / prev - 1.0
        prev = cur if cur is not None else None
    return out


def _bar_trade_date(bar: Mapping) -> Optional[str]:
    td = bar.get("trade_date")
    if td is None:
        return None
    if hasattr(td, "isoformat"):
        return td.isoformat()
    return str(td)[:10]


def _spine_closes_amounts(
    bars: Sequence[Mapping],
) -> tuple[list[str], list[Optional[float]], list[Optional[float]]]:
    dates: list[str] = []
    closes: list[Optional[float]] = []
    amounts: list[Optional[float]] = []
    for b in bars:
        td = _bar_trade_date(b)
        if td is None:
            continue
        dates.append(td)
        closes.append(_finite(b.get("close_qfq", b.get("close"))))
        amounts.append(_finite(b.get("amount")))
    return dates, closes, amounts


def _asof_index(dates: Sequence[str], trade_date: str) -> Optional[int]:
    for i in range(len(dates) - 1, -1, -1):
        if dates[i] == trade_date:
            return i
    return None


def _truthy(v: Any) -> bool:
    return bool(v)


def vol_expand_hit(row: Mapping, *, vol_expand_pctile: float) -> bool:
    if not _truthy(row.get("right_side")):
        return False
    if row.get("solar_term") not in _VOL_EXPAND_TERMS:
        return False
    sigma = _finite(row.get("_sigma_pctile"))
    if sigma is None:
        return False
    return sigma >= vol_expand_pctile


def _peer_ret_on_date(
    code: str,
    td: str,
    *,
    series_by_code: Mapping[str, Sequence[Mapping]],
    rets_cache: dict[str, tuple[list[str], list[Optional[float]]]],
) -> Optional[float]:
    if code not in rets_cache:
        bars = series_by_code.get(code) or []
        dates, closes, _amts = _spine_closes_amounts(bars)
        rets_cache[code] = (dates, daily_returns(closes))
    dates, rets = rets_cache[code]
    idx = _asof_index(dates, td)
    if idx is None:
        return None
    return rets[idx]


def champagne_hit(
    code: str,
    *,
    champ_k: int,
    champ_excess: float,
    peer_codes: Sequence[str],
    series_by_code: Mapping[str, Sequence[Mapping]],
    trade_date: str,
    rets_cache: dict[str, tuple[list[str], list[Optional[float]]]],
) -> bool:
    bars = series_by_code.get(code) or []
    dates, closes, _amts = _spine_closes_amounts(bars)
    t = _asof_index(dates, trade_date)
    if t is None or t + 1 < champ_k:
        return False
    own_rets = daily_returns(closes)
    start = t + 1 - champ_k
    excess_sum = 0.0
    for i in range(start, t + 1):
        ret = own_rets[i]
        if _finite(ret) is None:
            return False
        td = dates[i]
        peer_rets: list[float] = []
        for pc in peer_codes:
            pr = _peer_ret_on_date(
                pc, td, series_by_code=series_by_code, rets_cache=rets_cache
            )
            fv = _finite(pr)
            if fv is not None:
                peer_rets.append(fv)
        if not peer_rets:
            return False
        med = statistics.median(peer_rets)
        if ret <= med:
            return False
        excess_sum += ret - med
    return excess_sum >= champ_excess


def danger_hit(
    *,
    closes: Sequence[Any],
    amounts: Sequence[Any],
    t: int,
    vol_hist: int,
    danger_ret_pctile: float,
    danger_amt_pctile: float,
) -> bool:
    """Window-then-rank danger (Spec §3.2 / Spec C VOL). Not full-spine rank."""
    rets = daily_returns(closes)
    if t < 0 or t >= len(rets):
        return False
    if _finite(rets[t]) is None or _finite(amounts[t]) is None:
        return False
    start = max(0, t + 1 - vol_hist)
    ret_window = list(rets[start : t + 1])
    amt_window = list(amounts[start : t + 1])
    finite_ret_n = sum(1 for v in ret_window if _finite(v) is not None)
    finite_amt_n = sum(1 for v in amt_window if _finite(v) is not None)
    if finite_ret_n <= 1 or finite_amt_n <= 1:
        return False
    ret_scores = scores_0_100(ret_window)
    amt_scores = scores_0_100(amt_window)
    rs = ret_scores[-1]
    as_ = amt_scores[-1]
    if rs is None or as_ is None:
        return False
    p_ret = rs / 100.0
    p_amt = as_ / 100.0
    return p_ret <= danger_ret_pctile and p_amt >= danger_amt_pctile


def _rate(tagged: int, eligible: int) -> float:
    if eligible <= 0:
        return 0.0
    return tagged / eligible


def _warn_rate(kind: str, rate: float, cap: float, trade_date: str) -> None:
    print(
        f"WARN exit_tags tag_rate {kind} rate={rate:.4f} > cap={cap} "
        f"trade_date={trade_date}",
        file=sys.stderr,
    )


def assign_exit_tags(
    stock_rows: list[dict],
    l2_rows: list[dict],
    l1_rows: list[dict],
    *,
    params: MetricsParams,
    bar_cache: Mapping[str, Sequence[Mapping]],
    l2_synth_by_code: Mapping[str, Sequence[Mapping]],
    quarantine: set[str] | None = None,
    trade_date: str,
    enable_l2_danger: bool = False,
) -> dict:
    """Mutate only ``tags`` on rows; return rates_meta for stock/l2/l1."""
    qua = quarantine if quarantine is not None else set()

    if not params.exit_tags_enabled:
        for rows in (stock_rows, l2_rows, l1_rows):
            for r in rows:
                r["tags"] = []
        return {
            "stock": _rate(0, len(stock_rows)),
            "l2": _rate(0, len(l2_rows)),
            "l1": 0.0,
        }

    stock_peers = [
        r["ts_code"]
        for r in stock_rows
        if r.get("ts_code") is not None
        and stock_peer_eligible(r, quarantine=qua)
    ]
    l2_peers = [
        r["code"]
        for r in l2_rows
        if r.get("code") is not None and basket_peer_eligible(r)
    ]

    stock_rets_cache: dict[str, tuple[list[str], list[Optional[float]]]] = {}
    l2_rets_cache: dict[str, tuple[list[str], list[Optional[float]]]] = {}

    stock_tagged = 0
    for r in stock_rows:
        tags: list[str] = []
        ts = r.get("ts_code")
        if vol_expand_hit(r, vol_expand_pctile=params.vol_expand_pctile):
            tags.append("vol_expand")
        if ts is not None and champagne_hit(
            ts,
            champ_k=params.champ_k,
            champ_excess=params.champ_excess,
            peer_codes=stock_peers,
            series_by_code=bar_cache,
            trade_date=trade_date,
            rets_cache=stock_rets_cache,
        ):
            tags.append("champagne")
        bars = bar_cache.get(ts) if ts is not None else None
        if bars:
            dates, closes, amounts = _spine_closes_amounts(bars)
            t = _asof_index(dates, trade_date)
            if t is not None and danger_hit(
                closes=closes,
                amounts=amounts,
                t=t,
                vol_hist=params.vol_hist,
                danger_ret_pctile=params.danger_ret_pctile,
                danger_amt_pctile=params.danger_amt_pctile,
            ):
                tags.append("danger")
        r["tags"] = tags
        if tags:
            stock_tagged += 1

    l2_tagged = 0
    for r in l2_rows:
        tags = []
        code = r.get("code")
        if vol_expand_hit(r, vol_expand_pctile=params.vol_expand_pctile):
            tags.append("vol_expand")
        if code is not None and champagne_hit(
            code,
            champ_k=params.champ_k,
            champ_excess=params.champ_excess,
            peer_codes=l2_peers,
            series_by_code=l2_synth_by_code,
            trade_date=trade_date,
            rets_cache=l2_rets_cache,
        ):
            tags.append("champagne")
        if enable_l2_danger and code is not None:
            bars = l2_synth_by_code.get(code) or []
            dates, closes, amounts = _spine_closes_amounts(bars)
            t = _asof_index(dates, trade_date)
            if t is not None and danger_hit(
                closes=closes,
                amounts=amounts,
                t=t,
                vol_hist=params.vol_hist,
                danger_ret_pctile=params.danger_ret_pctile,
                danger_amt_pctile=params.danger_amt_pctile,
            ):
                tags.append("danger")
        r["tags"] = tags
        if tags:
            l2_tagged += 1

    for r in l1_rows:
        r["tags"] = []

    stock_rate = _rate(stock_tagged, len(stock_rows))
    l2_rate = _rate(l2_tagged, len(l2_rows))
    l1_rate = 0.0
    cap = params.tag_rate_cap
    if len(stock_rows) > 0 and stock_rate > cap:
        _warn_rate("stock", stock_rate, cap, trade_date)
    if len(l2_rows) > 0 and l2_rate > cap:
        _warn_rate("l2", l2_rate, cap, trade_date)

    return {"stock": stock_rate, "l2": l2_rate, "l1": l1_rate}
