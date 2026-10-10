"""Spec C digest: 「量」column scope + RS→VOL→amount sort on 右侧 Top."""
from __future__ import annotations

from scripts.common.db import get_conn, init_schema, upsert_daily_l1, upsert_daily_l2, upsert_daily_stock
from scripts.common.taxonomy_meta import load_l1_buckets
from scripts.issues.digest import _fmt_cell, render_l1_issue, render_radar_issue


def _seed_base(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    td = "2024-01-10"
    conn.execute(
        """
        INSERT INTO run_meta (
          trade_date, status, param_version, map_version, git_sha,
          bar_coverage, computable_coverage, limit_coverage_asof, tradable_count
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (td, "ok", "p05-v2", "p05-v1", "abc", 1.0, 1.0, 1.0, 3),
    )
    conn.commit()
    return conn, td


def test_fmt_cell_none_is_empty_string():
    assert _fmt_cell(None) == ""


def test_right_side_top_header_has_liang_and_sort_rs_vol_amount(tmp_path, monkeypatch):
    conn, td = _seed_base(tmp_path, monkeypatch)
    # Same RS: higher VOL first; same RS+VOL: higher amount first; higher RS first.
    upsert_daily_stock(
        conn,
        [
            {
                "trade_date": td,
                "ts_code": "A_hi_rs.SZ",
                "sw_l2_code": "801780",
                "l1_id": "l1_finance",
                "T": "热",
                "RS": 90.0,
                "VOL_score": 10.0,
                "right_side": 1,
                "solar_term": "谷雨",
                "amount": 1e8,
                "right_side_days_trading": 1,
            },
            {
                "trade_date": td,
                "ts_code": "B_mid_vol.SZ",
                "sw_l2_code": "801780",
                "l1_id": "l1_finance",
                "T": "热",
                "RS": 80.0,
                "VOL_score": 50.0,
                "right_side": 1,
                "solar_term": "谷雨",
                "amount": 1e8,
                "right_side_days_trading": 1,
            },
            {
                "trade_date": td,
                "ts_code": "C_lo_vol_hi_amt.SZ",
                "sw_l2_code": "801780",
                "l1_id": "l1_finance",
                "T": "热",
                "RS": 80.0,
                "VOL_score": 20.0,
                "right_side": 1,
                "solar_term": "谷雨",
                "amount": 9e9,
                "right_side_days_trading": 1,
            },
            {
                "trade_date": td,
                "ts_code": "D_same_vol_hi_amt.SZ",
                "sw_l2_code": "801780",
                "l1_id": "l1_finance",
                "T": "热",
                "RS": 80.0,
                "VOL_score": 20.0,
                "right_side": 1,
                "solar_term": "谷雨",
                "amount": 1e9,
                "right_side_days_trading": 1,
            },
        ],
    )
    conn.commit()
    md = render_l1_issue(conn, td, "l1_finance", name_zh="金融")
    top = md.split("## 右侧存续 Top")[1]
    assert (
        "| ts_code | 名称 | T | RS | 量 | 节气 | 交易日天数 | 成交额(亿) |" in top
    )
    # Order: A (RS90) → B (RS80,VOL50) → C (RS80,VOL20,amt9e9) → D (RS80,VOL20,amt1e9)
    pos = [top.index(c) for c in (
        "A_hi_rs.SZ",
        "B_mid_vol.SZ",
        "C_lo_vol_hi_amt.SZ",
        "D_same_vol_hi_amt.SZ",
    )]
    assert pos == sorted(pos)
    conn.close()


def test_l2_and_l1_headers_include_liang_warm_tables_do_not(tmp_path, monkeypatch):
    conn, td = _seed_base(tmp_path, monkeypatch)
    upsert_daily_stock(
        conn,
        [
            {
                "trade_date": td,
                "ts_code": "000001.SZ",
                "sw_l2_code": "801780",
                "l1_id": "l1_finance",
                "T": "热",
                "RS": 1.0,
                "VOL_score": 55.0,
                "right_side": 1,
                "tag_warm_to_hot": 1,
                "solar_term": "谷雨",
                "amount": 1e9,
                "right_side_days_trading": 2,
            }
        ],
    )
    upsert_daily_l2(
        conn,
        [
            {
                "trade_date": td,
                "code": "801780",
                "T": "热",
                "S_temp": 0.7,
                "RS": 1.0,
                "VOL_score": None,
                "right_side": 1,
                "tag_warm_to_hot": 1,
                "solar_term": "谷雨",
                "members_tradable": 1,
                "members_total": 1,
                "warm_to_hot_member_count": 1,
                "amount": 1e9,
            }
        ],
    )
    upsert_daily_l1(
        conn,
        [
            {
                "trade_date": td,
                "code": "l1_finance",
                "T": "凉",
                "S_temp": None,
                "RS": None,
                "VOL_score": None,
                "right_side": 0,
                "tag_warm_to_hot": 0,
                "solar_term": None,
                "members_tradable": 1,
                "members_total": 1,
                "warm_to_hot_member_count": 1,
                "amount": 1e9,
            }
        ],
    )
    conn.commit()

    l1_md = render_l1_issue(conn, td, "l1_finance", name_zh="金融")
    self_sec = l1_md.split("## L1 自身")[1].split("## 行业")[0]
    l2_sec = l1_md.split("## 行业（L2）扫描")[1].split("## 今日温转热")[0]
    warm_sec = l1_md.split("## 今日温转热")[1].split("## 今日温转平")[0]

    assert (
        "| T | l1_id | 名称 | RS | 量 | 在右侧 | 节气 | 今日温转热 | "
        "今日成分温转热 | 成分热以上 | 成交额(亿) |"
    ) in self_sec
    assert (
        "| T | 代码 | 名称 | RS | 量 | 在右侧 | 节气 | 今日温转热 | "
        "今日成分温转热 | 成分热以上 | 成交额(亿) |"
    ) in l2_sec
    warm_header = [ln for ln in warm_sec.splitlines() if ln.startswith("| ts_code")][0]
    assert warm_header == "| ts_code | 名称 | T | RS | 在右侧 | 节气 | 成交额(亿) |"
    assert "量" not in warm_header

    # Basket VOL null → empty「量」cell; footnote once on L1/L2 block
    assert "| 凉 | l1_finance | 金融 |  |  |" in self_sec
    assert "量" in l1_md and ("本 slice" in l1_md or "后放" in l1_md)

    radar = render_radar_issue(conn, td, load_l1_buckets())
    hot = radar.split("全市场温转热")[1]
    hot_header = [ln for ln in hot.splitlines() if ln.startswith("| ts_code")][0]
    assert hot_header == "| ts_code | 名称 | l1_id | T | RS | 成交额(亿) |"
    assert "量" not in hot_header
    conn.close()
