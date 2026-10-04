from datetime import date

import pytest

from scripts.fund_industry import (
    ReportUnavailableError,
    aggregate_report,
    build_classification_asof,
    fetch_latest_report,
    load_taxonomy,
    parse_report_date,
    resolve_l1,
    resolve_l2,
)


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy()


def test_taxonomy_matches_repository_spec(taxonomy):
    assert taxonomy.map_version == "sw2021-repo-v1"
    assert len(taxonomy.l1_by_id) == 14
    assert len(taxonomy.l2_by_code) == 134
    assert taxonomy.l1_by_id["l1_finance"]["name"] == "金融"
    assert taxonomy.l2_by_code["480300"]["name"] == "股份制银行Ⅱ"


def test_resolve_hierarchy_accepts_code_or_name_and_rejects_wrong_parent(taxonomy):
    l1 = resolve_l1("l1_health | 医药健康", taxonomy)
    assert l1["id"] == "l1_health"
    assert resolve_l2("370100", "l1_health", taxonomy)["name"] == "化学制药"
    assert resolve_l2("化学制药", "l1_health", taxonomy)["code"] == "370100"
    with pytest.raises(ValueError, match="belongs to"):
        resolve_l2("480300", "l1_health", taxonomy)
    with pytest.raises(ValueError, match="unknown L2"):
        resolve_l2("软件开发", "l1_health", taxonomy)


def test_report_date_requires_supported_quarter_end():
    assert parse_report_date("20260630") == date(2026, 6, 30)
    with pytest.raises(ValueError, match="quarter reporting date"):
        parse_report_date("2026-06-29")
    with pytest.raises(ValueError, match="predates"):
        parse_report_date("20210630")


def test_asof_classification_rolls_l3_to_l2_and_ignores_future_rows(taxonomy):
    history = [
        {"symbol": "000001", "start_date": "2021-07-30", "industry_code": "480301", "update_time": "2021-07-30"},
        {"symbol": "000001", "start_date": "2026-05-01", "industry_code": "480302", "update_time": "2026-05-03"},
        {"symbol": "600000", "start_date": "2024-02-01", "industry_code": "490100", "update_time": "2024-02-01"},
        {"symbol": "000002", "start_date": "2026-07-01", "industry_code": "430100", "update_time": "2026-07-02"},
    ]
    result = build_classification_asof(history, "2026-06-30", taxonomy)
    assert result["000001"] == {"l2_code": "480300", "l1_id": "l1_finance"}
    assert result["600000"] == {"l2_code": "490100", "l1_id": "l1_finance"}
    assert "000002" not in result


def test_aggregate_market_value_proportions_and_coverage(taxonomy):
    records = [
        {"股票代码": "000001", "报告期": "2026-06-30", "持股总市值": 10000},
        {"股票代码": "000001", "报告期": "2026-06-30", "持股总市值": 5000},
        {"股票代码": "600000", "报告期": "2026-06-30", "持股总市值": 30000},
        {"股票代码": "000002", "报告期": "2026-06-30", "持股总市值": 20000},
        {"股票代码": "300001", "报告期": "2026-06-30", "持股总市值": 50000},
        {"股票代码": "830001", "报告期": "2026-06-30", "持股总市值": 7000},
        {"股票代码": "00700", "报告期": "2026-06-30", "持股总市值": 9000},
        {"股票代码": "000003", "报告期": "2026-06-30", "持股总市值": 10000},
    ]
    classification = {
        "000001": {"l2_code": "480300", "l1_id": "l1_finance"},
        "600000": {"l2_code": "480300", "l1_id": "l1_finance"},
        "000002": {"l2_code": "370100", "l1_id": "l1_health"},
        "300001": {"l2_code": "270100", "l1_id": "l1_tech_hw"},
    }
    result = aggregate_report(
        records,
        classification,
        taxonomy,
        l1_id="l1_finance",
        l2_code="480300",
        report_date="20260630",
    )
    assert result["market_value_亿元"]["all_source_reported_stock_positions"] == 14.1
    assert result["market_value_亿元"]["repository_scope_a_shares"] == 12.5
    assert result["market_value_亿元"]["sw2021_mapped_a_shares"] == 11.5
    assert result["market_value_亿元"]["selected_l1"] == 4.5
    assert result["market_value_亿元"]["selected_l2"] == 4.5
    assert result["proportion_pct"]["selected_l1_of_mapped_a_share_holdings"] == 39.1304
    assert result["proportion_pct"]["selected_l2_of_mapped_a_share_holdings"] == 39.1304
    assert result["market_value_亿元"]["out_of_repository_scope_securities"] == 1.6
    assert result["coverage"]["source_record_count"] == 8
    assert result["coverage"]["distinct_source_security_count"] == 7
    assert result["coverage"]["unmapped_a_share_count"] == 1
    assert result["coverage"]["out_of_repository_scope_security_count"] == 2
    assert "基金净资产" in result["interpretation"][0]


def test_latest_report_skips_not_yet_published_quarter():
    calls = []

    def fake_fetch(period):
        calls.append(period)
        if period == date(2026, 6, 30):
            return [{"报告期": period.isoformat(), "股票代码": "000001", "持股总市值": 100}]
        return []

    report_date, rows = fetch_latest_report(as_of=date(2026, 10, 4), fetcher=fake_fetch)
    assert report_date == date(2026, 6, 30)
    assert len(rows) == 1
    assert calls[:2] == [date(2026, 9, 30), date(2026, 6, 30)]


def test_explicit_unavailable_report_does_not_silently_fall_back():
    with pytest.raises(ReportUnavailableError, match="2026-09-30"):
        fetch_latest_report(
            report_date="20260930",
            fetcher=lambda _period: [],
        )


def test_unexpected_report_period_fails_closed():
    with pytest.raises(RuntimeError, match="unexpected report dates"):
        fetch_latest_report(
            report_date="20260630",
            fetcher=lambda _period: [{"报告期": "2026-03-31", "股票代码": "000001", "持股总市值": 100}],
        )
