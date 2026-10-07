import json

from scripts.common.db import get_conn, init_schema
from scripts.issues.update_l1_issues import (
    live_publish_allowed,
    main,
    trade_date_from_heartbeat,
)


def _write_nested(path, *, status="ok", asof="2024-01-10",
                  days=None, statuses=None, date=None):
    days = days or ["2024-01-08", "2024-01-10"]
    statuses = statuses or ["ok", "ok"]
    job = {"status": status, "asof": asof, "days": days, "statuses": statuses}
    if date is not None:
        job["date"] = date
    path.write_text(
        json.dumps({"updated_at": "t", "daily_run": job}),
        encoding="utf-8",
    )


def test_nested_heartbeat_trade_date(tmp_path):
    path = tmp_path / "heartbeat.json"
    _write_nested(path)
    td, reason = trade_date_from_heartbeat(str(path))
    assert reason == "ok" and td == "2024-01-10"


def test_nested_heartbeat_asof_dates_full_prefix(tmp_path):
    from scripts.eval.live_shadow_step import heartbeat_asof_dates
    path = tmp_path / "heartbeat.json"
    _write_nested(path)
    dates, reason = heartbeat_asof_dates(str(path))
    assert reason == "ok"
    assert dates == ["2024-01-08", "2024-01-10"]


def test_nested_heartbeat_skip_blocks_publish(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    conn.execute(
        """INSERT INTO run_meta (
             trade_date, status, param_version, map_version,
             bar_coverage, computable_coverage, limit_coverage_asof, tradable_count
           ) VALUES (?,?,?,?,?,?,?,?)""",
        ("2024-01-10", "ok", "p05-v1", "p05-v1", 1.0, 1.0, 1.0, 1),
    )
    conn.commit()
    path = tmp_path / "heartbeat.json"
    _write_nested(path, status="skip", date="2024-01-10", asof="2024-01-10",
                  days=["2024-01-10"], statuses=["skip"])
    ok, why = live_publish_allowed(conn, "2024-01-10", heartbeat_path=str(path))
    assert not ok and why == "skip"
    conn.close()


def test_heartbeat_skip_no_ops(tmp_path, monkeypatch):
    hb = tmp_path / "heartbeat.json"
    hb.write_text(
        json.dumps({"job": "daily_run", "status": "skip", "date": "2024-01-06"}),
        encoding="utf-8",
    )
    d, reason = trade_date_from_heartbeat(str(hb))
    assert d is None and reason == "skip"

    monkeypatch.setattr(
        "scripts.issues.update_l1_issues.DEFAULT_DB", str(tmp_path / "trend.db")
    )
    rc = main(["--from-heartbeat", "--dry-run", "--out-dir", str(tmp_path / "out")])
    assert rc == 0
    assert not (tmp_path / "out").exists()


def test_heartbeat_uses_last_processed_day(tmp_path, monkeypatch):
    hb = tmp_path / "heartbeat.json"
    hb.write_text(
        json.dumps(
            {
                "status": "ok",
                "asof": "2024-01-10",
                "days": ["2024-01-08", "2024-01-09", "2024-01-10"],
            }
        ),
        encoding="utf-8",
    )
    d, reason = trade_date_from_heartbeat(str(hb))
    assert reason == "ok" and d == "2024-01-10"


def test_date_live_skips_when_heartbeat_skip_same_day(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    monkeypatch.setattr(
        "scripts.issues.update_l1_issues.DEFAULT_DB", str(tmp_path / "trend.db")
    )
    conn = get_conn()
    init_schema(conn)
    conn.execute(
        """
        INSERT INTO run_meta (
          trade_date, status, param_version, map_version,
          bar_coverage, computable_coverage, limit_coverage_asof, tradable_count
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        ("2024-01-06", "ok", "p05-v1", "p05-v1", 1.0, 1.0, 1.0, 1),
    )
    conn.commit()
    (tmp_path / "heartbeat.json").write_text(
        json.dumps({"status": "skip", "date": "2024-01-06"}),
        encoding="utf-8",
    )
    ok, why = live_publish_allowed(conn, "2024-01-06")
    assert ok is False and why == "skip"
    conn.close()
    published = []
    monkeypatch.setattr(
        "scripts.issues.update_l1_issues.publish_live",
        lambda *a, **k: published.append(1) or {},
    )
    rc = main(
        [
            "--date",
            "2024-01-06",
            "--live",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    assert published == []


def test_live_skips_missing_and_fail_run_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    conn.execute(
        """
        INSERT INTO run_meta (
          trade_date, status, param_version, map_version,
          bar_coverage, computable_coverage, limit_coverage_asof, tradable_count
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        ("2024-01-10", "fail", "p05-v1", "p05-v1", 0.0, 0.0, 0.0, 0),
    )
    conn.commit()
    ok, why = live_publish_allowed(conn, "2024-01-10")
    assert ok is False and why == "fail"
    ok, why = live_publish_allowed(conn, "2024-01-09")
    assert ok is False and why == "missing_run_meta"
    conn.execute("UPDATE run_meta SET status='partial' WHERE trade_date='2024-01-10'")
    conn.commit()
    ok, why = live_publish_allowed(conn, "2024-01-10")
    assert ok is True and why == "ok"
    conn.close()
