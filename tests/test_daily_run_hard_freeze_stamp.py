# tests/test_daily_run_hard_freeze_stamp.py
from datetime import date

from scripts.common.bars import bars_conn
from scripts.common.hard_freeze import write_hard_freeze_pass_meta
from scripts.daily_run import main
from scripts.taxonomy.unmapped import UnmappedMetrics


def _ok_um(**k):
    return UnmappedMetrics(
        unmapped_count=0,
        ipo_unmapped_alert_count=0,
        yaml_quarantine_size=0,
        clist_fetch="ok",
    )


def test_daily_run_fails_without_stamp(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    bars_conn(str(db))
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof])
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    called = {"n": 0}

    def _pd(*a, **k):
        called["n"] += 1
        return "ok"

    monkeypatch.setattr("scripts.daily_run.process_day", _pd)
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 1
    assert called["n"] == 0


def test_daily_run_ok_with_matching_stamp(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=20, param_version="p05-v3")
    conn.close()
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof])
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    monkeypatch.setattr("scripts.daily_run.process_day", lambda *a, **k: "ok")
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 0


def test_daily_run_fails_n_mismatch(tmp_path, monkeypatch):
    """Spec §5.3: stamp N ≠ yaml → daily_run non-zero; process_day not called."""
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=99, param_version="p05-v3")
    conn.close()
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof])
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    called = {"n": 0}
    monkeypatch.setattr(
        "scripts.daily_run.process_day",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "ok",
    )
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 1
    assert called["n"] == 0


def test_daily_run_fails_param_version_mismatch(tmp_path, monkeypatch):
    """Spec §5.4: stamp param_version ≠ yaml → daily_run non-zero."""
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=20, param_version="old-pv")
    conn.close()
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof])
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    called = {"n": 0}
    monkeypatch.setattr(
        "scripts.daily_run.process_day",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "ok",
    )
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 1
    assert called["n"] == 0


def test_skip_non_trading_no_stamp_required(tmp_path, monkeypatch):
    db = tmp_path / "b.db"
    bars_conn(str(db))
    calls = {"n": 0}

    def _check(*a, **k):
        calls["n"] += 1
        return 0

    # Requires Task 2 Step 3 module-level import into scripts.daily_run
    monkeypatch.setattr("scripts.daily_run.check_hard_freeze_stamp", _check)
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 6)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: False)
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-06", "--bars-db", str(db)])
    assert rc == 0
    assert calls["n"] == 0  # Spec §5.11: skip path must not call check


def test_check_called_once_before_process_day(tmp_path, monkeypatch):
    """Spec §5.11: when computing, check exactly once; not inside process_day."""
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=20, param_version="p05-v3")
    conn.close()
    calls = {"check": 0, "pd": 0}

    def _check(bars_path=None, yaml_path=None):
        calls["check"] += 1
        return 0

    def _pd(*a, **k):
        calls["pd"] += 1
        return "ok"

    monkeypatch.setattr("scripts.daily_run.check_hard_freeze_stamp", _check)
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof, asof])
    # two days in queue — check must still be once (not per process_day)
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    monkeypatch.setattr("scripts.daily_run.process_day", _pd)
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 0
    assert calls["check"] == 1
    assert calls["pd"] == 2
