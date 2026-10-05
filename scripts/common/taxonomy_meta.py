"""Canonical L1 bucket meta (taxonomy §3.3 / ops §5 titles)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = _ROOT / "config" / "taxonomy" / "l1_buckets.yaml"

RADAR_TITLE = "[Radar] A股战场"
L1_DASHBOARD_LABEL = "l1-dashboard"
RADAR_DASHBOARD_LABEL = "radar-dashboard"


@dataclass(frozen=True)
class L1Bucket:
    l1_id: str
    name_zh: str
    sort: int


def load_l1_buckets(path: Optional[str | Path] = None) -> list[L1Bucket]:
    p = Path(path) if path else Path(os.environ.get("L1_BUCKETS_YAML") or _DEFAULT)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rows = data.get("l1") or data.get("l1_ids") or []
    out: list[L1Bucket] = []
    for i, row in enumerate(rows):
        if isinstance(row, str):
            out.append(L1Bucket(l1_id=row, name_zh=row, sort=(i + 1) * 10))
            continue
        lid = str(row["l1_id"])
        out.append(
            L1Bucket(
                l1_id=lid,
                name_zh=str(row.get("name_zh") or lid),
                sort=int(row.get("sort") or (i + 1) * 10),
            )
        )
    out.sort(key=lambda b: b.sort)
    return out


def l1_issue_title(bucket: L1Bucket) -> str:
    return "[L1] %s (%s)" % (bucket.name_zh, bucket.l1_id)
