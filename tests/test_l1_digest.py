from __future__ import annotations

from scripts.common.db import (
    get_conn,
    init_schema,
    upsert_daily_l1,
    upsert_daily_l2,
    upsert_daily_stock,
)
from scripts.common.taxonomy_meta import load_l1_buckets
from scripts.issues import digest
from scripts.issues.digest import render_l1_issue, render_radar_issue


def _fixture_stock_names(monkeypatch, rows):
    """Seed stock name_zh without relying on production YAML."""
    monkeypatch.setattr(digest, "load_stock_sw_l2", lambda path=None: list(rows))


def _seed(tmp_path, monkeypatch):
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
        (td, "ok", "p05-v1", "p05-v1", "abc123", 1.0, 1.0, 1.0, 3),
    )
    upsert_daily_stock(
        conn,
        [
            {
                "trade_date": td,
                "ts_code": "000001.SZ",
                "sw_l2_code": "801780",
                "l1_id": "l1_finance",
                "T": "热",
                "S_temp": 0.8,
                "RS": 1.2,
                "right_side": 1,
                "tag_warm_to_hot": 1,
                "tag_warm_to_flat": 0,
                "solar_term": "谷雨",
                "amount": 1e9,
                "right_side_days_trading": 2,
                "right_side_days_natural": 3,
            },
            {
                "trade_date": td,
                "ts_code": "600519.SH",
                "sw_l2_code": "801120",
                "l1_id": "l1_staples",
                "T": "温",
                "S_temp": 0.4,
                "RS": 0.5,
                "right_side": 0,
                "tag_warm_to_hot": 0,
                "tag_warm_to_flat": 0,
                "solar_term": "惊蛰",
                "amount": 2e9,
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
                "right_side": 1,
                "tag_warm_to_hot": 1,
                "solar_term": "谷雨",
                "members_tradable": 2,
                "members_total": 2,
                "warm_to_hot_member_count": 1,
                "amount": 1e9,
            }
        ],
    )
    conn.execute(
        """
        INSERT INTO signal_event (
          trade_date, ts_code, l1_id, sw_l2_code, event, T, detail, superseded_by
        ) VALUES (?,?,?,?,?,?,?,NULL)
        """,
        (td, "000002.SZ", "l1_finance", "801780", "EXIT_RIGHT", "凉", "{}"),
    )
    conn.commit()
    return conn, td


def _seed_with_daily_l1(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    upsert_daily_l1(
        conn,
        [
            {
                "trade_date": td,
                "code": "l1_finance",
                "T": "凉",
                "S_temp": None,
                "RS": None,
                "right_side": 0,
                "tag_warm_to_hot": 0,
                "tag_warm_to_flat": 0,
                "solar_term": None,
                "members_tradable": 1,
                "members_total": 2,
                "warm_to_hot_member_count": 1,
                "amount": 1e9,
            }
        ],
    )
    conn.commit()
    return conn, td


def test_l1_issue_has_self_section(tmp_path, monkeypatch):
    conn, td = _seed_with_daily_l1(tmp_path, monkeypatch)
    md = render_l1_issue(conn, td, "l1_finance", name_zh="金融")
    assert "## L1 自身" in md
    head = md.split("## 行业")[0]
    assert "同引擎" not in head
    assert "成分温转热" in head
    assert "| 凉 | l1_finance | 金融 |  | " in md or "| 凉 | l1_finance | 金融 | |" in md
    conn.close()


def test_radar_stock_warm_header_and_footnote(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    md = render_radar_issue(conn, td, load_l1_buckets())
    assert "| L1 | l1_id | T* | 个股 | 右侧 | 右侧占比 | 个股温转热 |" in md
    assert "按 l1_id" in md
    assert "L1 自身" in md
    conn.close()


def test_l1_self_section_empty_when_no_daily_l1_row(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    md = render_l1_issue(conn, td, "l1_health", name_zh="医药健康")
    assert "## L1 自身" in md
    head = md.split("## 行业")[0]
    assert "成分温转热" in head
    assert "同引擎" not in head
    # no daily_l1 → engine cells empty (not fabricated 0 / 凉)
    assert "|  | l1_health | 医药健康 |  |  |  |  |  |  |" in head or (
        "|  | l1_health | 医药健康 |  |  |  |  |  |" in head
    )
    conn.close()


def test_render_l1_issue_has_as_of_and_warm_to_hot(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    body = render_l1_issue(conn, td, "l1_finance", name_zh="金融")
    assert "as_of=%s" % td in body
    assert "param=p05-v1" in body
    assert "## 今日温转热" in body
    assert "000001.SZ" in body
    assert "## 今日温转平 / 结束右侧" in body
    assert "EXIT_RIGHT" in body
    assert "801780" in body
    conn.close()


def test_empty_l1_still_has_skeleton(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    body = render_l1_issue(conn, td, "l1_health", name_zh="医药健康")
    assert "as_of=%s" % td in body
    assert "## 行业（L2）扫描" in body
    assert "## 今日温转热" in body
    conn.close()


def test_l2_scan_uses_daily_stock_not_stub_map(tmp_path, monkeypatch):
    """L2 codes come from that day's daily_stock.sw_l2_code, not STUB_L1_TO_L2."""
    conn, td = _seed(tmp_path, monkeypatch)
    upsert_daily_stock(
        conn,
        [
            {
                "trade_date": td,
                "ts_code": "000999.SZ",
                "sw_l2_code": "801150",
                "l1_id": "l1_health",
                "T": "温",
                "right_side": 0,
                "amount": 1.0,
            }
        ],
    )
    upsert_daily_l2(
        conn,
        [
            {
                "trade_date": td,
                "code": "801150",
                "T": "温",
                "S_temp": 0.2,
                "right_side": 0,
                "solar_term": "惊蛰",
                "members_tradable": 1,
                "members_total": 1,
            }
        ],
    )
    body = render_l1_issue(conn, td, "l1_health", name_zh="医药健康")
    assert "801150" in body
    conn.close()


def test_radar_overview(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    body = render_radar_issue(conn, td, load_l1_buckets())
    assert "as_of=%s" % td in body
    assert "温转热=1" in body
    assert "l1_finance" in body
    assert "000001.SZ" in body
    conn.close()


def test_radar_t_star_uses_temperature_rank_not_unicode_max(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    upsert_daily_stock(
        conn,
        [
            {
                "trade_date": td,
                "ts_code": "601318.SH",
                "sw_l2_code": "801780",
                "l1_id": "l1_finance",
                "T": "沸",
                "right_side": 1,
                "amount": 1.0,
            }
        ],
    )
    body = render_radar_issue(conn, td, load_l1_buckets())
    finance_row = [line for line in body.splitlines() if "| 金融 |" in line][0]
    # Unicode MAX(T) would pick 热 over 沸; rank(T) must pick 沸.
    assert finance_row.split("|")[3].strip() == "沸"
    conn.close()


def test_meta_header_prefers_actions_run_url(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "financeView/trending")
    monkeypatch.setenv("GITHUB_RUN_ID", "99")
    body = render_l1_issue(conn, td, "l1_finance", name_zh="金融")
    assert "https://github.com/financeView/trending/actions/runs/99" in body
    conn.close()


def test_l2_scan_headers_and_yi_and_names(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    upsert_daily_stock(
        conn,
        [
            {
                "trade_date": td,
                "ts_code": "300016.SZ",
                "sw_l2_code": "370100",
                "l1_id": "l1_health",
                "T": "凉",
                "tag_warm_to_hot": 1,
                "amount": 1.065e9,
            },
            {
                "trade_date": td,
                "ts_code": "000999.SZ",
                "sw_l2_code": "370200",
                "l1_id": "l1_health",
                "T": "温",
                "tag_warm_to_hot": 0,
                "amount": None,
            },
        ],
    )
    upsert_daily_l2(
        conn,
        [
            {
                "trade_date": td,
                "code": "370100",
                "T": "凉",
                "S_temp": 0.1,
                "RS": 0.2,
                "right_side": 0,
                "tag_warm_to_hot": 0,
                "solar_term": "霜降",
                "members_tradable": 1,
                "members_total": 1,
                "warm_to_hot_member_count": 1,
                "amount": 1.065e9,
            },
            {
                "trade_date": td,
                "code": "370200",
                "T": "温",
                "S_temp": 0.3,
                "RS": 0.4,
                "right_side": 0,
                "tag_warm_to_hot": 0,
                "solar_term": "惊蛰",
                "members_tradable": 1,
                "members_total": 1,
                "warm_to_hot_member_count": 0,
                "amount": None,
            },
        ],
    )
    conn.commit()
    body = render_l1_issue(conn, td, "l1_health", name_zh="医药健康")
    assert "| T | 代码 | 名称 | RS | 右侧 | 节气 | 温转热 | 成分温转热 | 成交额(亿) |" in body
    assert "化学制药" in body
    assert "10.650" in body
    assert "1.065e+09" not in body
    assert "0.000" not in body  # NULL amount must not render as zero
    conn.close()


def test_stock_tables_keep_ts_code_add_name_column(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    _fixture_stock_names(
        monkeypatch,
        [
            {"ts_code": "000001.SZ", "sw_l2_code": "801780", "name_zh": "平安银行"},
            {"ts_code": "000002.SZ", "sw_l2_code": "801780", "name_zh": "万科A"},
        ],
    )
    body = render_l1_issue(conn, td, "l1_finance", name_zh="金融")
    assert "| ts_code | 名称 |" in body
    assert "| ts_code | 名称 | event | T | detail |" in body
    assert "平安银行" in body
    assert "万科A" in body
    assert "成交额(亿)" in body
    assert "10.000" in body
    conn.close()


def test_radar_hot_top_has_name_and_yi(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    _fixture_stock_names(
        monkeypatch,
        [
            {"ts_code": "000001.SZ", "sw_l2_code": "801780", "name_zh": "平安银行"},
        ],
    )
    body = render_radar_issue(conn, td, load_l1_buckets())
    hot_section = body.split("全市场温转热")[1][:200]
    assert "名称" in hot_section
    assert "成交额(亿)" in body
    assert "平安银行" in body
    assert "10.000" in body
    conn.close()
