from datetime import date

from scripts.common.calendar import (
    clear_trade_date_cache,
    load_trade_dates_from_list,
    next_trade_date,
    prev_trade_date,
)
from scripts.common.coverage import CoverageMetrics, evaluate_ok
from scripts.common.ts_code import is_ts_code, to_sina_symbol, to_ts_code


def test_ts_code_roundtrip():
    assert to_ts_code("000001") == "000001.SZ"
    assert to_ts_code("600000") == "600000.SH"
    assert to_ts_code("sh600519") == "600519.SH"
    assert to_sina_symbol("600519.SH") == "sh600519"
    assert is_ts_code("000001.SZ")
    assert not is_ts_code("000001")


def test_fri_to_mon_next_trade_date():
    clear_trade_date_cache()
    load_trade_dates_from_list(
        ["2024-01-05", "2024-01-08", "2024-01-09"]  # Fri, Mon, Tue
    )
    fri = date(2024, 1, 5)
    assert next_trade_date(fri) == date(2024, 1, 8)
    assert prev_trade_date(date(2024, 1, 8)) == fri


def test_ok_history_without_limits():
    D = date(2024, 1, 5)
    asof = date(2024, 1, 10)
    m = CoverageMetrics(
        bar_coverage=0.95,
        computable_coverage=0.6,
        limit_coverage_asof=0.0,  # history may lack vendor limits
    )
    d = evaluate_ok(D, asof, m)
    assert d.ok
    assert d.status == "ok"
    assert d.apply_limit_gate is False


def test_ok_asof_requires_limits():
    asof = date(2024, 1, 10)
    m = CoverageMetrics(
        bar_coverage=0.95,
        computable_coverage=0.6,
        limit_coverage_asof=0.5,
    )
    d = evaluate_ok(asof, asof, m)
    assert not d.ok
    assert d.status == "partial"
    assert "limit_coverage" in d.reason


def test_ok_asof_with_limits():
    asof = date(2024, 1, 10)
    m = CoverageMetrics(
        bar_coverage=0.95,
        computable_coverage=0.6,
        limit_coverage_asof=0.85,
    )
    d = evaluate_ok(asof, asof, m)
    assert d.ok
    assert d.apply_limit_gate is True


def test_bars_schema_roundtrip(tmp_path):
    from scripts.common.bars import bars_conn

    db = tmp_path / "bars.db"
    conn = bars_conn(str(db))
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, open_qfq, close_qfq, open_raw, close_raw, bar_source)
        VALUES ('000001.SZ', '2024-01-05', 10.0, 10.5, 11.0, 11.2, 'sina')
        """
    )
    conn.commit()
    row = conn.execute(
        "SELECT open_raw, close_qfq FROM bars WHERE ts_code='000001.SZ'"
    ).fetchone()
    assert row == (11.0, 10.5)
    conn.close()


def test_gold_fixture_exists():
    import csv
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "fixtures" / "temp_raw_gold.csv"
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 5
    assert "expect_T_raw" in rows[0]
