"""l2_members_map must stay on taxonomy §4; never emit 801xxx ghosts."""
from pathlib import Path

from scripts.common.universe import l2_members_map, load_stock_sw_l2, section4_codes


def test_l2_members_map_skips_801_and_non_section4(tmp_path):
    p = tmp_path / "stock_sw_l2.yaml"
    p.write_text(
        "map_version: sw2021-v1\n"
        "members:\n"
        "  - {ts_code: 000001.SZ, sw_l2_code: '370100'}\n"
        "  - {ts_code: 600519.SH, sw_l2_code: '801780'}\n"
        "  - {ts_code: 000002.SZ, sw_l2_code: '999999'}\n",
        encoding="utf-8",
    )
    mapping = l2_members_map(stock_path=str(p))
    assert "370100" in mapping
    assert "000001.SZ" in mapping["370100"]
    assert "801780" not in mapping
    assert "999999" not in mapping


def test_checked_in_l2_members_subset_of_section4():
    allowed = section4_codes()
    mapping = l2_members_map(
        stock_path=str(
            Path(__file__).resolve().parents[1]
            / "config"
            / "taxonomy"
            / "stock_sw_l2.yaml"
        )
    )
    assert mapping
    assert all(code in allowed for code in mapping)
    assert not any(code.startswith("801") for code in mapping)


def test_empty_section4_boards_have_no_members():
    """本地生活等 §4 码无 A 股成分 → 无 daily_l2 行是预期，不是幽灵板。"""
    from collections import Counter

    from scripts.common.universe import load_l2_to_l1

    counts = Counter(
        r["sw_l2_code"] for r in load_stock_sw_l2() if r.get("sw_l2_code")
    )
    empty = sorted(
        r["code"] for r in load_l2_to_l1() if counts[r["code"]] == 0
    )
    assert "460700" in empty  # 本地生活服务Ⅱ
    assert "720800" in empty  # 社交Ⅱ
    assert "480600" in empty  # 其他银行Ⅱ
