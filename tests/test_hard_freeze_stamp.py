# tests/test_hard_freeze_stamp.py
from pathlib import Path

from scripts.common.bars import bars_conn
from scripts.common.hard_freeze import (
    check_hard_freeze_stamp,
    ensure_hard_freeze_pass_meta,
    load_hard_freeze_pass_config,
    read_hard_freeze_pass_meta,
    resolve_metrics_yaml_path,
    write_hard_freeze_pass_meta,
)


def test_resolve_respects_env(tmp_path, monkeypatch):
    p = tmp_path / "m.yaml"
    p.write_text("param_version: t\nhard_freeze_min_suspend_days: 7\n", encoding="utf-8")
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(p))
    assert resolve_metrics_yaml_path() == Path(p)


def test_load_pass_config_reads_n_and_version(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "param_version: p-test\nhard_freeze_min_suspend_days: 11\n",
        encoding="utf-8",
    )
    cfg = load_hard_freeze_pass_config(p)
    assert cfg.min_suspend_days == 11
    assert cfg.param_version == "p-test"


def test_write_read_stamp_roundtrip(tmp_path):
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_hard_freeze_pass_meta(conn)
    write_hard_freeze_pass_meta(
        conn, n=20, param_version="p05-v3", rows_touched=42, rewritten_at="2026-10-10T00:00:00Z"
    )
    meta = read_hard_freeze_pass_meta(conn)
    assert meta["n"] == 20
    assert meta["param_version"] == "p05-v3"
    assert meta["rows_touched"] == 42
    assert meta["rewritten_at"] == "2026-10-10T00:00:00Z"


def test_write_upserts_single_row(tmp_path):
    conn = bars_conn(str(tmp_path / "b.db"))
    write_hard_freeze_pass_meta(conn, n=20, param_version="a")
    write_hard_freeze_pass_meta(conn, n=25, param_version="b")
    n = conn.execute("SELECT COUNT(*) FROM hard_freeze_pass_meta").fetchone()[0]
    assert n == 1
    assert read_hard_freeze_pass_meta(conn)["n"] == 25


def test_check_ok_mismatch_missing(tmp_path, monkeypatch):
    db = tmp_path / "b.db"
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(db))
    assert check_hard_freeze_stamp(str(db)) == 1  # missing
    write_hard_freeze_pass_meta(conn, n=20, param_version="p05-v3")
    assert check_hard_freeze_stamp(str(db)) == 0
    write_hard_freeze_pass_meta(conn, n=99, param_version="p05-v3")
    assert check_hard_freeze_stamp(str(db)) == 1  # N mismatch
    write_hard_freeze_pass_meta(conn, n=20, param_version="other")
    assert check_hard_freeze_stamp(str(db)) == 1  # param_version mismatch


def test_check_and_stamp_homologous_under_env_distinct_from_default(
    tmp_path, monkeypatch
):
    """Spec §5.10: METRICS_PARAMS_YAML values ≠ default file; write+check agree."""
    db = tmp_path / "b.db"
    y = tmp_path / "m.yaml"
    # Must differ from config/metrics/a_share_daily.yaml (p05-v3 / 20)
    y.write_text(
        "param_version: p-env-distinct\nhard_freeze_min_suspend_days: 13\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=13, param_version="p-env-distinct")
    assert check_hard_freeze_stamp(str(db)) == 0
    # If check ignored env and read default yaml, stamp would mismatch → 1
    monkeypatch.delenv("METRICS_PARAMS_YAML")
    assert check_hard_freeze_stamp(str(db)) == 1
