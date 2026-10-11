"""Exit-tags digest: 「止盈」column on stock Top / 温转热 / L2 (Spec §3.5)."""
from __future__ import annotations

from scripts.common.db import get_conn, init_schema, upsert_daily_l1, upsert_daily_l2, upsert_daily_stock
from scripts.common.taxonomy_meta import load_l1_buckets
from scripts.issues.digest import render_l1_issue, render_radar_issue


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


def test_right_warm_l2_show_zhiying_display_empty_ok(tmp_path, monkeypatch):
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
                "RS": 90.0,
                "VOL_score": 40.0,
                "right_side": 1,
                "tag_warm_to_hot": 1,
                "solar_term": "谷雨",
                "amount": 1e9,
                "right_side_days_trading": 2,
                "tags": '["vol_expand"]',
            },
            {
                "trade_date": td,
                "ts_code": "000002.SZ",
                "sw_l2_code": "801780",
                "l1_id": "l1_finance",
                "T": "热",
                "RS": 80.0,
                "VOL_score": 20.0,
                "right_side": 1,
                "tag_warm_to_hot": 1,
                "solar_term": "谷雨",
                "amount": 5e8,
                "right_side_days_trading": 1,
                "tags": "[]",
            },
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
                "members_tradable": 2,
                "members_total": 2,
                "warm_to_hot_member_count": 1,
                "amount": 1e9,
                "tags": '["vol_expand", "champagne"]',
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
                "members_tradable": 2,
                "members_total": 2,
                "warm_to_hot_member_count": 1,
                "amount": 1e9,
                "tags": "[]",
            }
        ],
    )
    conn.execute(
        """
        INSERT INTO signal_event (
          trade_date, ts_code, l1_id, sw_l2_code, event, T, detail, superseded_by
        ) VALUES (?,?,?,?,?,?,?,NULL)
        """,
        (td, "000003.SZ", "l1_finance", "801780", "EXIT_RIGHT", "凉", "{}"),
    )
    conn.commit()

    md = render_l1_issue(conn, td, "l1_finance", name_zh="金融")

    self_sec = md.split("## L1 自身")[1].split("## 行业")[0]
    assert "止盈" not in self_sec

    l2_sec = md.split("## 行业（L2）扫描")[1].split("## 今日温转热")[0]
    assert (
        "| T | 代码 | 名称 | RS | 量 | 止盈 | 在右侧 | 节气 | 今日温转热 | "
        "今日成分温转热 | 成分热以上 | 成交额(亿) |"
    ) in l2_sec
    assert "波动率放大、开香槟" in l2_sec

    warm_sec = md.split("## 今日温转热")[1].split("## 今日温转平")[0]
    warm_header = [ln for ln in warm_sec.splitlines() if ln.startswith("| ts_code")][0]
    assert warm_header == (
        "| ts_code | 名称 | T | RS | 止盈 | 在右侧 | 节气 | 成交额(亿) |"
    )
    assert "波动率放大" in warm_sec
    # empty tags → empty cell between RS and 在右侧 for 000002
    row2 = [ln for ln in warm_sec.splitlines() if "000002.SZ" in ln][0]
    cells2 = [c.strip() for c in row2.strip("|").split("|")]
    # ts_code 名称 T RS 止盈 在右侧 节气 成交额
    assert cells2[3] in ("80", "80.0")
    assert cells2[4] == ""
    assert cells2[5] == "是"

    exit_sec = md.split("## 今日温转平 / 结束右侧")[1].split("## 右侧存续")[0]
    assert "止盈" not in exit_sec

    top = md.split("## 右侧存续 Top")[1]
    assert (
        "| ts_code | 名称 | T | RS | 量 | 止盈 | 节气 | 交易日天数 | 成交额(亿) |"
        in top
    )
    assert "波动率放大" in top

    radar = render_radar_issue(conn, td, load_l1_buckets())
    radar_l1 = radar.split("## 按 L1")[1].split("## 全市场温转热")[0]
    assert "止盈" not in radar_l1

    conn.close()


def test_null_tags_render_empty_zhiying_cell(tmp_path, monkeypatch):
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
                "RS": 90.0,
                "VOL_score": 40.0,
                "right_side": 1,
                "tag_warm_to_hot": 1,
                "solar_term": "谷雨",
                "amount": 1e9,
                "right_side_days_trading": 2,
                "tags": None,
            }
        ],
    )
    conn.commit()
    md = render_l1_issue(conn, td, "l1_finance", name_zh="金融")
    top = md.split("## 右侧存续 Top")[1]
    assert "止盈" in top
    row = [ln for ln in top.splitlines() if "000001.SZ" in ln][0]
    cells = [c.strip() for c in row.strip("|").split("|")]
    # ts_code 名称 T RS 量 止盈 节气 交易日天数 成交额
    assert cells[5] == ""
    assert cells[6] == "谷雨"
    conn.close()
