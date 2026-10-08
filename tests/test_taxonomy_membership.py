from scripts.taxonomy.membership import (
    bump_map_version,
    guard_ok,
    membership_delta,
    semantic_equal,
)


def test_bump_map_version():
    assert bump_map_version("sw2021-v1") == "sw2021-v2"
    assert bump_map_version("sw2021-v12") == "sw2021-v13"


def test_bump_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        bump_map_version("p05-v1")


def test_membership_delta_and_guard():
    head = [
        {"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": "A"},
        {"ts_code": "000002.SZ", "sw_l2_code": "370100", "name_zh": None},
    ]
    cand = [
        {"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": "A"},
        {"ts_code": "000003.SZ", "sw_l2_code": "480300", "name_zh": "C"},
    ]
    adds, deletes, changes = membership_delta(head, cand)
    assert (adds, deletes, changes) == (1, 1, 0)
    assert guard_ok(5508, 5508, 10, 0, 0) is True
    assert guard_ok(5508, 4000, 0, 0, 0) is False  # < 0.8
    assert guard_ok(5508, 5508, 50, 40, 0) is False  # 90 > 80


def test_name_only_semantically_differs_but_no_sw_change():
    a = [{"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": "旧"}]
    b = [{"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": "新"}]
    assert semantic_equal(a, b) is False
    assert membership_delta(a, b) == (0, 0, 0)


def test_mapped_count_skips_null_sw_l2():
    from scripts.taxonomy.membership import mapped_count

    members = [
        {"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": None},
        {"ts_code": "000002.SZ", "sw_l2_code": None, "name_zh": None},
    ]
    assert mapped_count(members, {"370100"}) == 1


def test_patch_map_version_header_only_first_line(tmp_path):
    from scripts.taxonomy.membership import patch_map_version_header

    p = tmp_path / "sw_l2_to_l1.yaml"
    p.write_text(
        "map_version: sw2021-v1\n"
        "l2:\n"
        "  - {code: '370100', l1_id: l1_a, name_zh: x}\n",
        encoding="utf-8",
    )
    patch_map_version_header(str(p), "sw2021-v2")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("map_version: sw2021-v2\n")
    assert "370100" in text and "l1_a" in text
