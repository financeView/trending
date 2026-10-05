from scripts.common.db import get_conn, init_schema, upsert_daily_stock
from scripts.issues.update_l1_issues import main


def test_dry_run_writes_fourteen_plus_radar(tmp_path, monkeypatch):
    db = tmp_path / "trend.db"
    monkeypatch.setenv("TREND_DB", str(db))
    conn = get_conn()
    init_schema(conn)
    td = "2024-01-10"
    conn.execute(
        """
        INSERT INTO run_meta (
          trade_date, status, param_version, map_version,
          bar_coverage, computable_coverage, limit_coverage_asof, tradable_count
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (td, "ok", "p05-v1", "p05-v1", 1.0, 1.0, 1.0, 1),
    )
    upsert_daily_stock(
        conn,
        [
            {
                "trade_date": td,
                "ts_code": "000001.SZ",
                "l1_id": "l1_finance",
                "T": "热",
                "tag_warm_to_hot": 1,
                "right_side": 1,
                "amount": 1.0,
            }
        ],
    )
    conn.close()

    out = tmp_path / "issues"
    rc = main(["--date", td, "--dry-run", "--out-dir", str(out)])
    assert rc == 0
    files = sorted(p.name for p in out.iterdir())
    assert "radar.md" in files
    assert "l1_finance.md" in files
    assert "l1_health.md" in files
    assert len(files) == 15
    text = (out / "l1_finance.md").read_text(encoding="utf-8")
    assert "as_of=%s" % td in text
    assert "今日温转热" in text
