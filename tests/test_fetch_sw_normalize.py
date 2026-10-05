"""Normalize vendor SW classify rows onto taxonomy §4 L2 codes."""
from scripts.taxonomy.fetch_sw_members import dump_yaml, normalize_member


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
