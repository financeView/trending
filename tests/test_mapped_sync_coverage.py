"""mapped_sync_coverage: synced stub names cannot ok a large map."""
from datetime import date

from scripts.common.bars import apply_flag_rows, bars_conn
from scripts.common.coverage import CoverageMetrics, compute_coverage_from_bars, evaluate_ok


def test_five_synced_of_hundred_not_ok(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    D = date(2024, 1, 10)
    mapped = ["%06d.SZ" % i for i in range(1, 101)]
    for ts in mapped[:5]:
        conn.execute(
            """
            INSERT INTO bars (
              ts_code, trade_date, open_qfq, high_qfq, low_qfq, close_qfq,
              open_raw, high_raw, low_raw, close_raw, bar_source
            ) VALUES (?, ?, 1,1,1,1, 1,1,1,1, 'sina')
            """,
            (ts, D.isoformat()),
        )
        apply_flag_rows(conn, [(ts, D.isoformat(), 0, 0)])
    conn.commit()
    m = compute_coverage_from_bars(conn, D, universe=mapped, quarantine=[], min_history=1)
    assert m.mapped_size == 100
    assert m.mapped_sync_coverage == 0.05
    d = evaluate_ok(D, D, m)
    assert not d.ok
    assert "mapped_sync" in d.reason
    conn.close()


def test_history_ok_still_needs_mapped_sync():
    m = CoverageMetrics(
        bar_coverage=0.95,
        computable_coverage=0.6,
        limit_coverage_asof=0.0,
        mapped_size=100,
        mapped_sync_coverage=0.5,
    )
    d = evaluate_ok(date(2024, 1, 5), date(2024, 1, 10), m)
    assert not d.ok
    assert "mapped_sync" in d.reason
