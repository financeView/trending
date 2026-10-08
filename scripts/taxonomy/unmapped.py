"""Unmapped count + IPO≥3 alert (clist f26 / first_seen) for Spec D."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from scripts.common.calendar import trading_days_inclusive
from scripts.common.em_client import _infer_ts_code, fetch_clist_all_a
from scripts.common.universe import load_quarantine_codes, load_universe_codes

_SH_SZ = re.compile(r"^\d{6}\.(SH|SZ)$")
_TZ_SH = ZoneInfo("Asia/Shanghai")
_IPO_ALERT_DAYS = 3


@dataclass
class UnmappedMetrics:
    unmapped_count: Optional[int]
    ipo_unmapped_alert_count: Optional[int]
    yaml_quarantine_size: int
    clist_fetch: str  # ok|fail


def parse_em_list_date(f26_val: Any) -> Optional[date]:
    """Parse Eastmoney clist f26 (YYYYMMDD or ms epoch) → date; None if missing."""
    if f26_val is None or f26_val == "":
        return None
    if isinstance(f26_val, date) and not isinstance(f26_val, datetime):
        return f26_val
    if isinstance(f26_val, datetime):
        return f26_val.astimezone(_TZ_SH).date() if f26_val.tzinfo else f26_val.date()
    if isinstance(f26_val, (int, float)):
        ts = float(f26_val)
        if ts > 1e11:  # ms
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=_TZ_SH).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(f26_val).strip()
    if re.fullmatch(r"\d{8}", s):
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None
    if re.fullmatch(r"\d{13}", s) or re.fullmatch(r"\d{10}", s):
        try:
            return parse_em_list_date(int(s))
        except ValueError:
            return None
    return None


def clist_row_to_ts_code(row: dict) -> Optional[str]:
    """Map EM clist row → SH/SZ ts_code; reject BJ / non-matches."""
    if not isinstance(row, dict):
        return None
    raw_ts = row.get("ts_code")
    if raw_ts not in (None, ""):
        ts = str(raw_ts)
        return ts if _SH_SZ.match(ts) else None
    inferred = _infer_ts_code(row.get("f12"), row)
    if not inferred:
        return None
    return inferred if _SH_SZ.match(inferred) else None


def _default_clist_fetch() -> Any:
    return fetch_clist_all_a(["f12", "f13", "f14", "f26"])


def _iter_clist_dicts(raw: Any) -> Iterable[dict]:
    if raw is None:
        return
    if hasattr(raw, "iterrows"):
        for _, r in raw.iterrows():
            yield dict(r.to_dict()) if hasattr(r, "to_dict") else dict(r)
        return
    for row in raw:
        if isinstance(row, dict):
            yield row


def _load_first_seen(path: str) -> dict[str, str]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _write_first_seen(path: str, data: dict[str, str]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def compute_unmapped_metrics(
    *,
    session_asof: date,
    first_seen_path: str,
    clist_rows: Optional[list] = None,
    clist_fetch: Optional[Callable[..., Any]] = None,
) -> UnmappedMetrics:
    """Compute |clist−mapped| and IPO≥3 alerts; update first_seen for new unmapped.

    Pass either ``clist_rows`` (tests may inject ``ts_code``+``f26``) or ``clist_fetch``
    (callable; default production fetch). On fetch failure return NULL counts (never 0).
    """
    quarantine = load_quarantine_codes()
    yaml_quarantine_size = len(quarantine)

    rows_src: Any
    if clist_rows is not None:
        rows_src = clist_rows
    else:
        fetch = clist_fetch or _default_clist_fetch
        try:
            rows_src = fetch()
        except Exception:
            return UnmappedMetrics(
                unmapped_count=None,
                ipo_unmapped_alert_count=None,
                yaml_quarantine_size=yaml_quarantine_size,
                clist_fetch="fail",
            )

    mapped = set(load_universe_codes())
    first_seen = _load_first_seen(first_seen_path)
    first_seen_dirty = False

    # ts_code → f26 raw
    clist_f26: dict[str, Any] = {}
    for row in _iter_clist_dicts(rows_src):
        ts = clist_row_to_ts_code(row)
        if not ts:
            continue
        clist_f26[ts] = row.get("f26")

    unmapped = sorted(set(clist_f26) - mapped)
    ipo_alert = 0
    asof_s = session_asof.isoformat()

    for ts in unmapped:
        list_date = parse_em_list_date(clist_f26.get(ts))
        if list_date is None:
            if ts not in first_seen:
                first_seen[ts] = asof_s
                first_seen_dirty = True
            try:
                list_date = date.fromisoformat(str(first_seen[ts])[:10])
            except ValueError:
                continue
        else:
            # Record first observation even when f26 present (stable first_asof).
            if ts not in first_seen:
                first_seen[ts] = asof_s
                first_seen_dirty = True

        if list_date > session_asof:
            continue
        days = trading_days_inclusive(list_date, session_asof)
        if len(days) >= _IPO_ALERT_DAYS:
            ipo_alert += 1

    if first_seen_dirty:
        _write_first_seen(first_seen_path, first_seen)

    return UnmappedMetrics(
        unmapped_count=len(unmapped),
        ipo_unmapped_alert_count=ipo_alert,
        yaml_quarantine_size=yaml_quarantine_size,
        clist_fetch="ok",
    )
