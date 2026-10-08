import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.taxonomy.fetch_sw_members import dump_yaml
from scripts.taxonomy.refresh_taxonomy import refresh_taxonomy_once


def _cp(rc=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _no_clist_network(monkeypatch):
    """Step f must not hit Eastmoney during unit tests."""
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.fetch_clist_all_a",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network in unit test")),
    )


def test_dump_yaml_keeps_name_zh_and_version():
    text = dump_yaml(
        [{"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": ""}],
        map_version="sw2021-v3",
        prior_names={"000001.SZ": "平安银行"},
    )
    assert "map_version: sw2021-v3" in text
    assert "name_zh: 平安银行" in text


def test_dump_yaml_positional_still_works_for_normalize_tests():
    text = dump_yaml(
        [{"ts_code": "000001.SZ", "industry_code": "801780", "industry_name": "银行"}]
    )
    assert "801780" not in text
    assert "sw_l2_code: null" in text


def _seed_taxonomy_tree(root: Path) -> None:
    tax = root / "config" / "taxonomy"
    tax.mkdir(parents=True)
    (tax / "stock_sw_l2.yaml").write_text(
        "map_version: sw2021-v1\n"
        "members:\n"
        "  - {ts_code: 000001.SZ, sw_l2_code: '370100', name_zh: 旧名}\n",
        encoding="utf-8",
    )
    (tax / "sw_l2_to_l1.yaml").write_text(
        "map_version: sw2021-v1\nl2:\n  - {code: '370100', l1_id: l1_a}\n",
        encoding="utf-8",
    )
    (tax / "l1_buckets.yaml").write_text(
        "map_version: sw2021-v1\nl1:\n  - {l1_id: l1_a}\n",
        encoding="utf-8",
    )


def test_refresh_vendor_fail_keeps_yaml(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    stock = tmp_path / "config" / "taxonomy" / "stock_sw_l2.yaml"
    before = stock.read_bytes()

    def _boom():
        raise RuntimeError("vendor down")

    st = refresh_taxonomy_once(
        fetch_rows=_boom,
        name_map=lambda: {},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
        allowed={"370100"},
    )
    assert st["taxonomy_fetch"] == "fail"
    assert stock.read_bytes() == before


def test_refresh_guard_fail_keeps_yaml(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    stock = tmp_path / "config" / "taxonomy" / "stock_sw_l2.yaml"
    before = stock.read_bytes()

    # candidate empties mapped → fails 0.80× guard
    st = refresh_taxonomy_once(
        fetch_rows=lambda: [],
        name_map=lambda: {},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
        allowed={"370100"},
    )
    assert st["taxonomy_fetch"] == "fail"
    assert stock.read_bytes() == before


def test_refresh_name_only_writes_no_bump(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    rows = [{"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": "银行"}]
    st = refresh_taxonomy_once(
        fetch_rows=lambda: rows,
        name_map=lambda: {"000001.SZ": "新名"},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
        allowed={"370100"},
    )
    assert st["taxonomy_fetch"] == "ok"
    assert st["map_version"] == "sw2021-v1"
    text = (tmp_path / "config" / "taxonomy" / "stock_sw_l2.yaml").read_text(encoding="utf-8")
    assert "name_zh: 新名" in text


def test_refresh_membership_bump_three_headers(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    rows = [
        {"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": "银行"},
        {"ts_code": "000002.SZ", "industry_code": "370100", "industry_name": "万科"},
    ]
    st = refresh_taxonomy_once(
        fetch_rows=lambda: rows,
        name_map=lambda: {},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
        allowed={"370100"},
    )
    assert st["taxonomy_fetch"] == "ok"
    assert st["map_version"] == "sw2021-v2"
    for name in ("stock_sw_l2.yaml", "sw_l2_to_l1.yaml", "l1_buckets.yaml"):
        assert "map_version: sw2021-v2" in (
            tmp_path / "config" / "taxonomy" / name
        ).read_text(encoding="utf-8")


def test_cli_fetch_fail_exit_zero_writes_github_output(tmp_path, monkeypatch):
    from scripts.taxonomy import refresh_taxonomy as rt

    _seed_taxonomy_tree(tmp_path)
    out = tmp_path / "gh_out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.chdir(tmp_path)  # CLI repo_root = cwd
    monkeypatch.setattr(rt, "fetch_latest_rows", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    # default git=False; do not pass --git
    assert rt.main(["--asof", "2024-01-10"]) == 0
    body = out.read_text(encoding="utf-8")
    assert "taxonomy_fetch=fail" in body
    assert "taxonomy_head_sha=" in body  # empty value OK


def test_refresh_name_map_raises_keeps_prior_name(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    rows = [
        {"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": "银行"},
        {"ts_code": "000002.SZ", "industry_code": "370100", "industry_name": "万科"},
    ]

    def _boom():
        raise RuntimeError("name vendor down")

    st = refresh_taxonomy_once(
        fetch_rows=lambda: rows,
        name_map=_boom,
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
        allowed={"370100"},
    )
    assert st["taxonomy_fetch"] == "ok"
    text = (tmp_path / "config" / "taxonomy" / "stock_sw_l2.yaml").read_text(encoding="utf-8")
    assert "name_zh: 旧名" in text  # prior preserved; membership still wrote 000002
    assert "000002.SZ" in text


def test_publish_fail_prefers_upstream_over_pre_sha(monkeypatch):
    """Push-fail must hard-reset to @{upstream} first; never ORIG_HEAD."""
    from scripts.taxonomy import refresh_taxonomy as rt

    calls: list[tuple] = []
    pre_sha = "aaa111pre"
    upstream_sha = "ccc333up"  # published tip after rebase brought remote commits
    new_sha = "bbb222new"  # post-commit / ORIG_HEAD would be this

    def fake_git(repo_root, *args, check=True):
        calls.append(args)
        cmd = args[0] if args else ""
        if cmd == "diff" and "--cached" in args:
            return _cp(1)  # staged changes present
        if cmd == "rev-parse" and args[-1:] == ("HEAD",):
            # Before commit → pre_sha; after commit success path would see new_sha
            if any(c[0] == "commit" for c in calls[:-1]):
                return _cp(0, new_sha + "\n")
            return _cp(0, pre_sha + "\n")
        if cmd == "rev-parse" and "@{upstream}" in args:
            return _cp(0, upstream_sha + "\n")
        if cmd == "rev-parse" and "ORIG_HEAD" in args:
            return _cp(0, new_sha + "\n")
        if cmd == "pull":
            return _cp(0)
        if cmd == "push":
            return _cp(1, stderr="rejected")
        if cmd == "reset":
            return _cp(0)
        return _cp(0)

    monkeypatch.setattr(rt, "_git", fake_git)
    monkeypatch.delenv("TAXONOMY_HEAD_SHA", raising=False)

    status, sha = rt._publish_taxonomy_yaml("/tmp/fake-repo")
    assert status == "push_fail"
    assert sha == ""

    # pre_sha captured before commit
    commit_idx = next(i for i, c in enumerate(calls) if c[0] == "commit")
    first_head_idx = next(
        i for i, c in enumerate(calls) if c[0] == "rev-parse" and c[-1:] == ("HEAD",)
    )
    assert first_head_idx < commit_idx

    # Prefer @{upstream} over stale pre_sha; never ORIG_HEAD / checkout-only
    assert ("reset", "--hard", upstream_sha) in calls
    assert ("reset", "--hard", pre_sha) not in calls
    assert not any("ORIG_HEAD" in c for c in calls)
    assert not any(c[0] == "checkout" for c in calls)
    assert not rt.os.environ.get("TAXONOMY_HEAD_SHA")


def test_publish_fail_falls_back_to_pre_sha_without_upstream(monkeypatch):
    """When @{upstream} is unavailable, restore uses pre-commit SHA."""
    from scripts.taxonomy import refresh_taxonomy as rt

    calls: list[tuple] = []
    pre_sha = "aaa111pre"

    def fake_git(repo_root, *args, check=True):
        calls.append(args)
        cmd = args[0] if args else ""
        if cmd == "diff" and "--cached" in args:
            return _cp(1)
        if cmd == "rev-parse" and args[-1:] == ("HEAD",):
            return _cp(0, pre_sha + "\n")
        if cmd == "rev-parse" and "@{upstream}" in args:
            return _cp(128, stderr="no upstream")
        if cmd == "pull":
            return _cp(0)
        if cmd == "push":
            return _cp(1, stderr="rejected")
        if cmd == "reset":
            return _cp(0)
        return _cp(0)

    monkeypatch.setattr(rt, "_git", fake_git)
    monkeypatch.delenv("TAXONOMY_HEAD_SHA", raising=False)

    status, sha = rt._publish_taxonomy_yaml("/tmp/fake-repo")
    assert status == "push_fail"
    assert sha == ""
    assert ("reset", "--hard", pre_sha) in calls
    assert not any("ORIG_HEAD" in c for c in calls)


def test_push_fail_heartbeat_reports_restored_map_version(tmp_path, monkeypatch):
    """After YAML restore, status/heartbeat map_version is head, not bumped."""
    from scripts.taxonomy import refresh_taxonomy as rt

    _seed_taxonomy_tree(tmp_path)
    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "data" / "unmapped_first_seen.json").write_text("{}", encoding="utf-8")

    def fake_git(repo_root, *args, check=True):
        cmd = args[0] if args else ""
        if cmd == "diff" and "--cached" in args:
            return _cp(1)
        if cmd == "rev-parse" and args[-1:] == ("HEAD",):
            return _cp(0, "preprepre\n")
        if cmd == "rev-parse" and "@{upstream}" in args:
            return _cp(0, "preprepre\n")
        if cmd == "pull":
            return _cp(0)
        if cmd == "push":
            return _cp(1, stderr="rejected")
        if cmd == "reset":
            # Simulate restore: rewrite YAML back to head_version
            tax = tmp_path / "config" / "taxonomy"
            for name in ("stock_sw_l2.yaml", "sw_l2_to_l1.yaml", "l1_buckets.yaml"):
                p = tax / name
                text = p.read_text(encoding="utf-8")
                p.write_text(
                    text.replace("map_version: sw2021-v2", "map_version: sw2021-v1"),
                    encoding="utf-8",
                )
            return _cp(0)
        return _cp(0)

    monkeypatch.setattr(rt, "_git", fake_git)
    monkeypatch.delenv("TAXONOMY_HEAD_SHA", raising=False)
    rows = [
        {"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": "银行"},
        {"ts_code": "000002.SZ", "industry_code": "370100", "industry_name": "万科"},
    ]
    st = refresh_taxonomy_once(
        fetch_rows=lambda: rows,
        name_map=lambda: {},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=True,
        allowed={"370100"},
        clist_rows=[{"ts_code": "000001.SZ", "f26": "20200101"}],
    )
    assert st["taxonomy_fetch"] == "push_fail"
    assert st["map_version"] == "sw2021-v1"
    hb = json.loads((tmp_path / "data" / "heartbeat.json").read_text(encoding="utf-8"))
    assert hb["taxonomy"]["map_version"] == "sw2021-v1"
    stock = (tmp_path / "config" / "taxonomy" / "stock_sw_l2.yaml").read_text(
        encoding="utf-8"
    )
    assert "map_version: sw2021-v1" in stock


def test_step_f_writes_heartbeat_taxonomy_no_last_success(tmp_path, monkeypatch):
    """Step f merges heartbeat.taxonomy without write_heartbeat last_success."""
    _seed_taxonomy_tree(tmp_path)
    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "data" / "unmapped_first_seen.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: ["000001.SZ"],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    rows = [{"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": "银行"}]
    st = refresh_taxonomy_once(
        fetch_rows=lambda: rows,
        name_map=lambda: {},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
        allowed={"370100"},
        clist_rows=[
            {"ts_code": "000001.SZ", "f26": "20200101"},
            {"ts_code": "000002.SZ", "f26": "20200101"},
        ],
    )
    assert st["taxonomy_fetch"] == "skipped_no_diff"
    assert st["clist_fetch"] == "ok"
    assert st["unmapped_count"] == 1
    hb = json.loads(
        (tmp_path / "data" / "heartbeat.json").read_text(encoding="utf-8")
    )
    tax = hb["taxonomy"]
    assert tax["taxonomy_fetch"] == "skipped_no_diff"
    assert tax["clist_fetch"] == "ok"
    assert tax["unmapped_count"] == 1
    assert tax["yaml_quarantine_size"] == 0
    assert "last_success" not in tax
    assert tax["taxonomy_commit"] in ("", "unpushed")


def test_step_f_exception_reports_real_quarantine_size(tmp_path, monkeypatch):
    from scripts.taxonomy.refresh_taxonomy import _step_f_unmapped_heartbeat

    _seed_taxonomy_tree(tmp_path)
    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "data" / "unmapped_first_seen.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.common.universe.load_quarantine_codes",
        lambda: {"000099.SZ", "000098.SZ"},
    )
    monkeypatch.setattr(
        "scripts.taxonomy.refresh_taxonomy.compute_unmapped_metrics",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    st = _step_f_unmapped_heartbeat(
        {"taxonomy_fetch": "fail", "map_version": "sw2021-v1", "taxonomy_commit": ""},
        session_asof=date(2024, 1, 10),
        repo_root=str(tmp_path),
        git=False,
        clist_rows=[{"ts_code": "000001.SZ", "f26": None}],
    )
    assert st["clist_fetch"] == "fail"
    assert st["yaml_quarantine_size"] == 2
