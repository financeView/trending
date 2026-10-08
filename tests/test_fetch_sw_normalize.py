"""Normalize vendor SW classify rows onto taxonomy §4 L2 codes."""
from scripts.taxonomy.fetch_sw_members import (
    _read_map_version_header,
    dump_yaml,
    normalize_member,
)


def test_801780_never_written():
    rows = [
        {
            "ts_code": "000001.SZ",
            "industry_code": "801780",
            "industry_name": "银行",
        }
    ]
    out = dump_yaml(rows)
    assert "801780" not in out
    assert "sw_l2_code: null" in out


def test_bj_dropped_from_universe_codes():
    mapped = normalize_member(
        ts_code="430047.BJ",
        industry_code="480301",
        industry_name="股份制银行Ⅱ",
    )
    assert mapped is None


def test_l3_code_maps_to_section4_l2():
    row = normalize_member(
        ts_code="000001.SZ",
        industry_code="480301",
        industry_name="ignored",
    )
    assert row == {"ts_code": "000001.SZ", "sw_l2_code": "480300"}


def test_exact_name_when_code_unknown():
    row = normalize_member(
        ts_code="600519.SH",
        industry_code="999999",
        industry_name="白酒Ⅱ",
    )
    assert row == {"ts_code": "600519.SH", "sw_l2_code": "340500"}


def test_dump_yaml_sorts_members_by_ts_code():
    rows = [
        {"ts_code": "600000.SH", "industry_code": "480300", "industry_name": ""},
        {"ts_code": "000001.SZ", "industry_code": "480300", "industry_name": ""},
    ]
    out = dump_yaml(rows, map_version="sw2021-v2")
    i0 = out.index("000001.SZ")
    i1 = out.index("600000.SH")
    assert i0 < i1


def test_read_map_version_header_keeps_bumped(tmp_path):
    p = tmp_path / "stock_sw_l2.yaml"
    p.write_text("map_version: sw2021-v3\nmembers:\n  []\n", encoding="utf-8")
    assert _read_map_version_header(str(p)) == "sw2021-v3"
