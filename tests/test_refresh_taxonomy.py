from datetime import date
from pathlib import Path

from scripts.taxonomy.fetch_sw_members import dump_yaml
from scripts.taxonomy.refresh_taxonomy import refresh_taxonomy_once


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
