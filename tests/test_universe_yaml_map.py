"""SW2021 §4 L2→L1 YAML loaders (empty stock map allowed)."""
import re
from pathlib import Path

import pytest
import yaml

from scripts.common.universe import load_l2_to_l1, load_stock_sw_l2, load_universe_codes

ROOT = Path(__file__).resolve().parents[1]
L2_YAML = ROOT / "config" / "taxonomy" / "sw_l2_to_l1.yaml"
L1_YAML = ROOT / "config" / "taxonomy" / "l1_buckets.yaml"


def test_every_section4_code_once_and_14_l1():
    rows = load_l2_to_l1()
    codes = [r["code"] for r in rows]
    assert len(codes) == 134
    assert len(set(codes)) == 134
    for c in codes:
        assert len(c) == 6 and c.isdigit()
        assert not c.startswith("801")
    l1_ids = {r["l1_id"] for r in rows}
    buckets = yaml.safe_load(L1_YAML.read_text(encoding="utf-8"))
    expected = {x["l1_id"] for x in buckets["l1"]}
    assert len(expected) == 14
    assert l1_ids == expected
    import re

    def _header_version(path: Path) -> str:
        meta = yaml.safe_load(path.read_text(encoding="utf-8"))
        v = meta["map_version"]
        assert re.fullmatch(r"sw2021-v\d+", str(v)), v
        return str(v)

    v_l2 = _header_version(L2_YAML)
    v_l1 = _header_version(L1_YAML)
    v_stock = _header_version(ROOT / "config" / "taxonomy" / "stock_sw_l2.yaml")
    assert v_l2 == v_l1 == v_stock


def test_empty_stock_map_ok(tmp_path):
    p = tmp_path / "stock_sw_l2.yaml"
    p.write_text("map_version: sw2021-v1\nmembers: []\n", encoding="utf-8")
    assert load_stock_sw_l2(str(p)) == []
    assert load_universe_codes(stock_path=str(p)) == []


def test_checked_in_map_is_mapped_sh_sz_universe():
    text = (ROOT / "config" / "taxonomy" / "stock_sw_l2.yaml").read_text(encoding="utf-8")
    assert not re.search(r"801\d{3}", text)
    assert ".BJ" not in text
    u = load_universe_codes(stock_path=str(ROOT / "config" / "taxonomy" / "stock_sw_l2.yaml"))
    assert len(u) >= 2000
    assert all(c.endswith((".SH", ".SZ")) for c in u)


def test_801xxx_does_not_enter_universe(tmp_path):
    p = tmp_path / "stock_sw_l2.yaml"
    p.write_text(
        "map_version: sw2021-v1\n"
        "members:\n"
        "  - {ts_code: 000001.SZ, sw_l2_code: '370100'}\n"
        "  - {ts_code: 600519.SH, sw_l2_code: '801780'}\n",
        encoding="utf-8",
    )
    u = load_universe_codes(stock_path=str(p))
    assert "000001.SZ" in u
    assert "600519.SH" not in u


def test_load_stock_sw_l2_passes_name_zh(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "map_version: sw2021-v1\nmembers:\n"
        "  - {ts_code: 000001.SZ, sw_l2_code: '480300', name_zh: 平安银行}\n"
        "  - {ts_code: 000002.SZ, sw_l2_code: '430100'}\n",
        encoding="utf-8",
    )
    rows = load_stock_sw_l2(str(p))
    by = {r["ts_code"]: r for r in rows}
    assert by["000001.SZ"]["name_zh"] == "平安银行"
    assert by["000002.SZ"].get("name_zh") in (None, "")
