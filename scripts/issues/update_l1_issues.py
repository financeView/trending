#!/usr/bin/env python3
"""Render / upsert L1 + Radar Issues from trend.db (ops §5)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common.db import DEFAULT_DB, get_conn, init_schema
from scripts.common.taxonomy_meta import (
    L1_DASHBOARD_LABEL,
    RADAR_DASHBOARD_LABEL,
    RADAR_TITLE,
    l1_issue_title,
    load_l1_buckets,
)
from scripts.issues.digest import render_l1_issue, render_radar_issue
from scripts.issues.github_issues import (
    default_repo,
    default_token,
    upsert_issue,
)


def _heartbeat_job_view(data: dict) -> dict:
    """Prefer nested daily_run job; fall back to flat top-level heartbeat."""
    job = data.get("daily_run")
    return job if isinstance(job, dict) else data


def trade_date_from_heartbeat(path: Optional[str] = None) -> tuple[Optional[str], str]:
    """Return (trade_date, reason). reason=skip → do not update Issues (ops §5.3)."""
    hb = path or os.path.join(os.path.dirname(DEFAULT_DB), "heartbeat.json")
    if not os.path.exists(hb):
        return None, "missing_heartbeat"
    try:
        data = json.loads(Path(hb).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "bad_heartbeat"
    view = _heartbeat_job_view(data)
    if view.get("status") == "skip":
        return None, "skip"
    days = view.get("days") or []
    if days:
        return str(days[-1]), "ok"
    asof = view.get("asof") or view.get("date")
    if asof:
        return str(asof), "ok"
    return None, "no_date"


def live_publish_allowed(
    conn,
    trade_date: str,
    *,
    heartbeat_path: Optional[str] = None,
) -> tuple[bool, str]:
    """Live upsert gate: skip non-trading same-day, missing run_meta, or fail.

    ``partial`` is allowed (honest coverage). ``ok`` is allowed.
    """
    hb = heartbeat_path or os.path.join(os.path.dirname(DEFAULT_DB), "heartbeat.json")
    if os.path.exists(hb):
        try:
            data = json.loads(Path(hb).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        view = _heartbeat_job_view(data)
        if view.get("status") == "skip":
            skip_day = str(view.get("date") or view.get("asof") or "")
            if skip_day == str(trade_date):
                return False, "skip"
    row = conn.execute(
        "SELECT status FROM run_meta WHERE trade_date=?", (trade_date,)
    ).fetchone()
    if row is None:
        return False, "missing_run_meta"
    if row[0] == "fail":
        return False, "fail"
    return True, "ok"


def render_all(conn, trade_date: str, *, top_n: int = 20) -> dict[str, str]:
    buckets = load_l1_buckets()
    out: dict[str, str] = {}
    for b in buckets:
        out[b.l1_id] = render_l1_issue(
            conn, trade_date, b.l1_id, name_zh=b.name_zh, top_n=top_n
        )
    out["radar"] = render_radar_issue(conn, trade_date, buckets, top_n=top_n)
    return out


def write_dry_run(bodies: dict[str, str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, body in bodies.items():
        name = "radar.md" if key == "radar" else "%s.md" % key
        (out_dir / name).write_text(body, encoding="utf-8")


def publish_live(bodies: dict[str, str], *, token: str, repo: str) -> dict[str, int]:
    buckets = {b.l1_id: b for b in load_l1_buckets()}
    numbers: dict[str, int] = {}
    for key, body in bodies.items():
        if key == "radar":
            title = RADAR_TITLE
            labels = [RADAR_DASHBOARD_LABEL]
        else:
            title = l1_issue_title(buckets[key])
            labels = [L1_DASHBOARD_LABEL]
        numbers[key] = upsert_issue(
            title=title, body=body, labels=labels, token=token, repo=repo
        )
    return numbers


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Update L1 / Radar GitHub Issues")
    p.add_argument("--date", default="", help="trade_date YYYY-MM-DD")
    p.add_argument(
        "--from-heartbeat",
        action="store_true",
        help="Use last processed day from data/heartbeat.json; no-op on status=skip",
    )
    p.add_argument("--dry-run", action="store_true", help="Write markdown files only")
    p.add_argument("--out-dir", default="output/issues")
    p.add_argument("--live", action="store_true", help="Upsert GitHub Issues")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--db", default="", help="override TREND_DB")
    args = p.parse_args(argv)

    if args.db:
        os.environ["TREND_DB"] = args.db
    if os.environ.get("SKIP_ISSUE_UPDATE", "").strip() in ("1", "true", "yes"):
        print("[issues] SKIP_ISSUE_UPDATE set; exit 0")
        return 0

    trade_date = args.date
    if args.from_heartbeat or not trade_date:
        trade_date, reason = trade_date_from_heartbeat()
        if reason == "skip":
            print("[issues] heartbeat status=skip; not updating Issues")
            return 0
        if not trade_date:
            print("[issues] no trade_date (%s); skip" % reason)
            return 0

    conn = get_conn()
    init_schema(conn)
    allowed, why = live_publish_allowed(conn, trade_date)
    if args.live and not allowed:
        print("[issues] skip live upsert (%s) date=%s" % (why, trade_date))
        conn.close()
        return 0
    if not args.live:
        meta = conn.execute(
            "SELECT status FROM run_meta WHERE trade_date=?", (trade_date,)
        ).fetchone()
        if meta is None:
            print("[issues] warn: no run_meta for %s" % trade_date, file=sys.stderr)

    bodies = render_all(conn, trade_date, top_n=args.top_n)
    conn.close()

    if args.dry_run or not args.live:
        write_dry_run(bodies, Path(args.out_dir))
        print("[issues] dry-run wrote %d files -> %s" % (len(bodies), args.out_dir))
        if not args.live:
            return 0

    token = default_token()
    repo = default_repo()
    if not token or not repo:
        print(
            "[issues] --live needs GITHUB_TOKEN and GITHUB_REPOSITORY",
            file=sys.stderr,
        )
        return 2
    nums = publish_live(bodies, token=token, repo=repo)
    print("[issues] upserted %d issues: %s" % (len(nums), nums))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
