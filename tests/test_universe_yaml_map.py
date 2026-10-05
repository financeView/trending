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
    meta = yaml.safe_load(L2_YAML.read_text(encoding="utf-8"))
    assert meta["map_version"] == "sw2021-v1"


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
