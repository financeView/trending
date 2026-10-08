#!/usr/bin/env python3
"""Taxonomy refresh: fetch → guard → write YAML → step f (unmapped/heartbeat).

CLI always exits 0; status via GITHUB_OUTPUT + return dict.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common.calendar import latest_trade_day
from scripts.common.universe import section4_codes
from scripts.taxonomy.fetch_sw_members import dump_yaml, fetch_latest_rows, normalize_member
from scripts.taxonomy.membership import (
    bump_map_version,
    guard_ok,
    load_members_from_yaml,
    mapped_count,
    membership_delta,
    patch_map_version_header,
    semantic_equal,
)
from scripts.taxonomy.patch_stock_names import _name_map
from scripts.taxonomy.unmapped import compute_unmapped_metrics

_TAXONOMY_FILES = (
    "config/taxonomy/stock_sw_l2.yaml",
    "config/taxonomy/sw_l2_to_l1.yaml",
    "config/taxonomy/l1_buckets.yaml",
)
_HEARTBEAT_REL = os.path.join("data", "heartbeat.json")
_FIRST_SEEN_REL = os.path.join("data", "unmapped_first_seen.json")
_HEARTBEAT_PUBLISH_FILES = (_HEARTBEAT_REL, _FIRST_SEEN_REL)


def _status(
    taxonomy_fetch: str,
    *,
    map_version: str = "",
    taxonomy_commit: str = "",
    adds: int = 0,
    deletes: int = 0,
    changes: int = 0,
    head_mapped: int = 0,
    cand_mapped: int = 0,
) -> dict:
    return {
        "taxonomy_fetch": taxonomy_fetch,
        "map_version": map_version,
        "taxonomy_commit": taxonomy_commit,
        "adds": adds,
        "deletes": deletes,
        "changes": changes,
        "head_mapped": head_mapped,
        "cand_mapped": cand_mapped,
    }


def _git(repo_root: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
    )


def _clear_taxonomy_head_sha() -> None:
    os.environ.pop("TAXONOMY_HEAD_SHA", None)


def _set_taxonomy_head_sha(sha: str) -> None:
    if sha:
        os.environ["TAXONOMY_HEAD_SHA"] = sha
    else:
        _clear_taxonomy_head_sha()


def _restore_taxonomy_to_published(repo_root: str, pre_sha: str = "") -> None:
    """Drop unpushed YAML commit; restore workspace to published tip.

    Prefer ``@{upstream}`` (remote-tracking tip after rebase) so the workspace
    matches published main when concurrent commits landed. Fall back to
    ``pre_sha`` (HEAD captured *before* ``git commit``) when upstream is
    unavailable (detached / no tracking). Never prefer post-commit
    ORIG_HEAD/HEAD — those can be the unpushed taxonomy commit.
    """
    candidates: list[str] = []
    up = _git(repo_root, "rev-parse", "--verify", "@{upstream}", check=False)
    if up.returncode == 0:
        tip = (up.stdout or "").strip()
        if tip:
            candidates.append(tip)
    if pre_sha and pre_sha not in candidates:
        candidates.append(pre_sha)
    for tip in candidates:
        # Hard reset drops the local unpushed commit; file checkout alone is not enough.
        r = _git(repo_root, "reset", "--hard", tip, check=False)
        if r.returncode == 0:
            return


def _publish_taxonomy_yaml(repo_root: str) -> tuple[str, str]:
    """Commit + rebase + push taxonomy YAML paths.

    Returns (taxonomy_fetch_suffix, sha_or_empty).
    On success: ("ok", sha). On failure: ("push_fail", "") after workspace restore.
    """
    pre_sha = ""
    try:
        _git(repo_root, "config", "user.email", "taxonomy-bot@users.noreply.github.com")
        _git(repo_root, "config", "user.name", "taxonomy-bot")
        _git(repo_root, "add", "--", *_TAXONOMY_FILES)
        staged = _git(repo_root, "diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            # nothing staged
            return "ok", ""
        # Capture tip *before* commit — post-commit ORIG_HEAD/HEAD are unsafe for restore.
        pre = _git(repo_root, "rev-parse", "HEAD", check=False)
        if pre.returncode == 0:
            pre_sha = (pre.stdout or "").strip()
        msg = "chore(taxonomy): refresh stock_sw_l2 snapshot"
        _git(repo_root, "commit", "-m", msg)
        pull = _git(
            repo_root,
            "pull",
            "--rebase",
            "--autostash",
            check=False,
        )
        if pull.returncode != 0:
            _git(repo_root, "rebase", "--abort", check=False)
            _restore_taxonomy_to_published(repo_root, pre_sha)
            _clear_taxonomy_head_sha()
            return "push_fail", ""
        push = _git(repo_root, "push", check=False)
        if push.returncode != 0:
            _restore_taxonomy_to_published(repo_root, pre_sha)
            _clear_taxonomy_head_sha()
            return "push_fail", ""
        sha = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
        _set_taxonomy_head_sha(sha)
        return "ok", sha
    except Exception:
        _git(repo_root, "rebase", "--abort", check=False)
        _restore_taxonomy_to_published(repo_root, pre_sha)
        _clear_taxonomy_head_sha()
        return "push_fail", ""


def merge_heartbeat_taxonomy(
    fields: dict[str, Any],
    path: Optional[str] = None,
) -> None:
    """Set ``data['taxonomy']=fields`` without ``write_heartbeat`` / last_success."""
    path = path or os.path.join(_ROOT, _HEARTBEAT_REL)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data: dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
            if isinstance(old, dict):
                data = old
        except Exception:
            data = {}
    data["taxonomy"] = dict(fields)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _publish_heartbeat_paths(repo_root: str) -> bool:
    """Commit+push heartbeat/first_seen. Never updates TAXONOMY_HEAD_SHA.

    On fail: restore workspace to pre-commit tip (same hard-reset contract as YAML).
    Returns True on success (or nothing staged), False on push/rebase fail.
    """
    pre_sha = ""
    try:
        _git(repo_root, "config", "user.email", "taxonomy-bot@users.noreply.github.com")
        _git(repo_root, "config", "user.name", "taxonomy-bot")
        _git(repo_root, "add", "--", *_HEARTBEAT_PUBLISH_FILES)
        staged = _git(repo_root, "diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            return True
        pre = _git(repo_root, "rev-parse", "HEAD", check=False)
        if pre.returncode == 0:
            pre_sha = (pre.stdout or "").strip()
        msg = "chore(taxonomy): heartbeat unmapped metrics"
        _git(repo_root, "commit", "-m", msg)
        pull = _git(
            repo_root,
            "pull",
            "--rebase",
            "--autostash",
            check=False,
        )
        if pull.returncode != 0:
            _git(repo_root, "rebase", "--abort", check=False)
            _restore_taxonomy_to_published(repo_root, pre_sha)
            return False
        push = _git(repo_root, "push", check=False)
        if push.returncode != 0:
            _restore_taxonomy_to_published(repo_root, pre_sha)
            return False
        # Intentionally do NOT set TAXONOMY_HEAD_SHA / taxonomy_head_sha.
        return True
    except Exception:
        _git(repo_root, "rebase", "--abort", check=False)
        _restore_taxonomy_to_published(repo_root, pre_sha)
        return False


def _step_f_unmapped_heartbeat(
    status: dict,
    *,
    repo_root: str,
    session_asof: date,
    git: bool,
    clist_rows: Optional[list] = None,
    clist_fetch: Optional[Callable[..., Any]] = None,
) -> dict:
    """Step f: clist metrics → first_seen → merge heartbeat.taxonomy; optional publish."""
    root = os.path.abspath(repo_root)
    hb_path = os.path.join(root, _HEARTBEAT_REL)
    fs_path = os.path.join(root, _FIRST_SEEN_REL)

    kwargs: dict[str, Any] = {
        "session_asof": session_asof,
        "first_seen_path": fs_path,
    }
    if clist_rows is not None:
        kwargs["clist_rows"] = clist_rows
    elif clist_fetch is not None:
        kwargs["clist_fetch"] = clist_fetch

    try:
        metrics = compute_unmapped_metrics(**kwargs)
    except Exception:
        from scripts.taxonomy.unmapped import UnmappedMetrics

        metrics = UnmappedMetrics(
            unmapped_count=None,
            ipo_unmapped_alert_count=None,
            yaml_quarantine_size=0,
            clist_fetch="fail",
        )

    updated_at = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    fields = {
        "taxonomy_fetch": status.get("taxonomy_fetch") or "fail",
        "clist_fetch": metrics.clist_fetch,
        "unmapped_count": metrics.unmapped_count,
        "ipo_unmapped_alert_count": metrics.ipo_unmapped_alert_count,
        "yaml_quarantine_size": metrics.yaml_quarantine_size,
        "map_version": status.get("map_version") or "",
        "taxonomy_commit": status.get("taxonomy_commit") or "",
        "updated_at": updated_at,
    }
    merge_heartbeat_taxonomy(fields, path=hb_path)

    status = dict(status)
    status["clist_fetch"] = metrics.clist_fetch
    status["unmapped_count"] = metrics.unmapped_count
    status["ipo_unmapped_alert_count"] = metrics.ipo_unmapped_alert_count
    status["yaml_quarantine_size"] = metrics.yaml_quarantine_size

    if git:
        _publish_heartbeat_paths(root)
    return status


def refresh_taxonomy_once(
    *,
    fetch_rows: Callable[[], list],
    name_map: Callable[[], dict[str, str]],
    repo_root: str,
    session_asof: date,
    git: bool = False,
    allowed: Optional[set[str]] = None,
    clist_rows: Optional[list] = None,
    clist_fetch: Optional[Callable[..., Any]] = None,
) -> dict:
    """Fetch → guard → write YAML → step f (unmapped / heartbeat / first_seen)."""
    root = os.path.abspath(repo_root)
    tax = os.path.join(root, "config", "taxonomy")
    stock_path = os.path.join(tax, "stock_sw_l2.yaml")
    l2_path = os.path.join(tax, "sw_l2_to_l1.yaml")
    l1_path = os.path.join(tax, "l1_buckets.yaml")

    if allowed is None:
        allowed = section4_codes(l2_path)

    head_version, head_members = load_members_from_yaml(stock_path)
    head_mapped = mapped_count(head_members, allowed)
    prior_names: dict[str, str] = {}
    for m in head_members:
        n = m.get("name_zh")
        if n not in (None, ""):
            prior_names[m["ts_code"]] = str(n)

    def _finish(st: dict) -> dict:
        return _step_f_unmapped_heartbeat(
            st,
            repo_root=root,
            session_asof=session_asof,
            git=git,
            clist_rows=clist_rows,
            clist_fetch=clist_fetch,
        )

    try:
        rows = list(fetch_rows() or [])
    except Exception:
        return _finish(_status("fail", map_version=head_version, head_mapped=head_mapped))

    cand_norms = []
    for row in rows:
        norm = normalize_member(
            row.get("ts_code") or "",
            str(row.get("industry_code") or ""),
            str(row.get("industry_name") or ""),
            allowed=allowed,
        )
        if norm is not None:
            cand_norms.append(norm)

    names = dict(prior_names)
    try:
        overlay = name_map() or {}
        for ts, name in overlay.items():
            if name not in (None, ""):
                names[str(ts)] = str(name)
    except Exception:
        pass

    cand_members = []
    for n in cand_norms:
        ts = n["ts_code"]
        cand_members.append(
            {
                "ts_code": ts,
                "sw_l2_code": n.get("sw_l2_code"),
                "name_zh": names.get(ts),
            }
        )
    cand_members.sort(key=lambda m: m["ts_code"])
    cand_mapped = mapped_count(cand_members, allowed)

    # empty mapped after normalize → fail (空帧 / 全未映射)
    if cand_mapped == 0:
        return _finish(
            _status(
                "fail",
                map_version=head_version,
                head_mapped=head_mapped,
                cand_mapped=cand_mapped,
            )
        )

    adds, deletes, changes = membership_delta(head_members, cand_members)
    if not guard_ok(head_mapped, cand_mapped, adds, deletes, changes):
        return _finish(
            _status(
                "fail",
                map_version=head_version,
                adds=adds,
                deletes=deletes,
                changes=changes,
                head_mapped=head_mapped,
                cand_mapped=cand_mapped,
            )
        )

    if semantic_equal(head_members, cand_members):
        return _finish(
            _status(
                "skipped_no_diff",
                map_version=head_version,
                adds=adds,
                deletes=deletes,
                changes=changes,
                head_mapped=head_mapped,
                cand_mapped=cand_mapped,
            )
        )

    membership_changed = (adds + deletes + changes) > 0
    if membership_changed:
        try:
            new_version = bump_map_version(head_version)
        except ValueError:
            return _finish(
                _status(
                    "fail",
                    map_version=head_version,
                    adds=adds,
                    deletes=deletes,
                    changes=changes,
                    head_mapped=head_mapped,
                    cand_mapped=cand_mapped,
                )
            )
    else:
        new_version = head_version

    text = dump_yaml(
        rows,
        map_version=new_version,
        prior_names=names,
        allowed=allowed,
    )
    with open(stock_path, "w", encoding="utf-8") as f:
        f.write(text)

    if membership_changed:
        patch_map_version_header(l2_path, new_version)
        patch_map_version_header(l1_path, new_version)

    taxonomy_commit = "unpushed"
    fetch_status = "ok"
    if git:
        pub, sha = _publish_taxonomy_yaml(root)
        if pub == "push_fail":
            # YAML restored to published tip; report that map_version, not the
            # rolled-back bump that is no longer on disk.
            return _finish(
                _status(
                    "push_fail",
                    map_version=head_version,
                    taxonomy_commit="unpushed",
                    adds=adds,
                    deletes=deletes,
                    changes=changes,
                    head_mapped=head_mapped,
                    cand_mapped=cand_mapped,
                )
            )
        taxonomy_commit = sha or "unpushed"
        fetch_status = "ok"

    return _finish(
        _status(
            fetch_status,
            map_version=new_version,
            taxonomy_commit=taxonomy_commit,
            adds=adds,
            deletes=deletes,
            changes=changes,
            head_mapped=head_mapped,
            cand_mapped=cand_mapped,
        )
    )


def _write_github_output(taxonomy_fetch: str, taxonomy_head_sha: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write("taxonomy_fetch=%s\n" % taxonomy_fetch)
        f.write("taxonomy_head_sha=%s\n" % taxonomy_head_sha)


def _parse_asof(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--git",
        action="store_true",
        help="Commit and push taxonomy YAML after a successful write",
    )
    p.add_argument(
        "--asof",
        default="",
        help="session_asof YYYY-MM-DD (default: latest_trade_day())",
    )
    p.add_argument(
        "--repo-root",
        default="",
        help="Repo root (default: cwd)",
    )
    args = p.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root or os.getcwd())
    session_asof = _parse_asof(args.asof) if args.asof else latest_trade_day()

    # Capture YAML publish SHA only; never re-rev-parse after a later heartbeat push.
    taxonomy_head_sha = ""
    try:
        st = refresh_taxonomy_once(
            fetch_rows=fetch_latest_rows,
            name_map=_name_map,
            repo_root=repo_root,
            session_asof=session_asof,
            git=bool(args.git),
        )
        taxonomy_fetch = str(st.get("taxonomy_fetch") or "fail")
        # Prefer env set at successful YAML publish; do not re-read HEAD.
        taxonomy_head_sha = os.environ.get("TAXONOMY_HEAD_SHA") or ""
        if taxonomy_fetch == "push_fail":
            taxonomy_head_sha = ""
            _clear_taxonomy_head_sha()
        elif taxonomy_fetch != "ok":
            # fail / skipped_no_diff with no YAML publish → empty
            taxonomy_head_sha = ""
        elif not args.git:
            taxonomy_head_sha = ""
    except Exception as exc:
        print("[refresh_taxonomy] unexpected error: %s" % exc, file=sys.stderr)
        taxonomy_fetch = "fail"
        taxonomy_head_sha = ""
        _clear_taxonomy_head_sha()

    _write_github_output(taxonomy_fetch, taxonomy_head_sha)
    print(
        "[refresh_taxonomy] taxonomy_fetch=%s taxonomy_head_sha=%s"
        % (taxonomy_fetch, taxonomy_head_sha or "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
