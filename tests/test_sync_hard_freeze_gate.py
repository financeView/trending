import datetime as dt

from scripts.common.bars import bars_conn
from scripts.common.hard_freeze import read_hard_freeze_pass_meta
from scripts.sync_bars_sample import main, run_spec_e_passes


def test_freeze_success_writes_stamp(tmp_path, monkeypatch):
    db = tmp_path / "b.db"
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(db))
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: 7,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "vendor_fields"})(),
    )
    run_spec_e_passes(conn, ["600000.SH"], session_asof=dt.date(2024, 1, 9))
    meta = read_hard_freeze_pass_meta(conn)
    assert meta["n"] == 20
    assert meta["param_version"] == "p-x"
    assert meta["rows_touched"] == 7


def test_freeze_raise_propagates_no_stamp(tmp_path, monkeypatch):
    conn = bars_conn(str(tmp_path / "b.db"))
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    try:
        run_spec_e_passes(conn, ["600000.SH"], session_asof=dt.date(2024, 1, 9))
        assert False, "expected raise"
    except RuntimeError:
        pass
    assert read_hard_freeze_pass_meta(conn) is None


def test_empty_codes_no_stamp(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(tmp_path / "b.db"))
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "vendor_fields"})(),
    )
    run_spec_e_passes(conn, [], session_asof=dt.date(2024, 1, 9))
    assert read_hard_freeze_pass_meta(conn) is None


def test_main_empty_mapped_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn",
        lambda: bars_conn(str(tmp_path / "b.db")),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day", lambda: dt.date(2024, 1, 9)
    )
    wrote = {"n": 0}

    def _wsc(*a, **k):
        wrote["n"] += 1

    monkeypatch.setattr("scripts.sync_bars_sample.write_sync_complete", _wsc)
    rc = main(["--end", "2024-01-09"])
    assert rc == 1
    assert wrote["n"] == 0


def test_main_freeze_fail_no_sync_complete_true(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn",
        lambda: bars_conn(str(tmp_path / "b.db")),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["600000.SH"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day", lambda: dt.date(2024, 1, 9)
    )

    def _boom(*a, **k):
        raise RuntimeError("freeze fail")

    monkeypatch.setattr("scripts.sync_bars_sample.run_spec_e_passes", _boom)
    outs = []

    def _wsc(complete, elapsed_min=0.0):
        outs.append(complete)

    monkeypatch.setattr("scripts.sync_bars_sample.write_sync_complete", _wsc)
    rc = main(["--end", "2024-01-09"])
    assert rc == 1
    assert outs == []  # must not write sync_complete on fail path


def test_stamp_write_fail_no_sync_complete(tmp_path, monkeypatch):
    """Spec §5.7: write_hard_freeze_pass_meta raise → sync non-zero, no sync_complete."""
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn",
        lambda: bars_conn(str(tmp_path / "b.db")),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["600000.SH"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day", lambda: dt.date(2024, 1, 9)
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: 1,
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.write_hard_freeze_pass_meta",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stamp fail")),
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "vendor_fields"})(),
    )
    outs = []
    monkeypatch.setattr(
        "scripts.sync_bars_sample.write_sync_complete",
        lambda complete, elapsed_min=0.0: outs.append(complete),
    )
    rc = main(["--end", "2024-01-09"])
    assert rc == 1
    assert outs == []


def test_board_calc_warn_does_not_block_stamp(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(tmp_path / "b.db"))
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: 1,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "board_calc_v1"})(),
    )
    monkeypatch.setattr(
        "scripts.common.board_calc.apply_board_calc",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bc")),
    )
    run_spec_e_passes(conn, ["600000.SH"], session_asof=dt.date(2024, 1, 9))
    assert read_hard_freeze_pass_meta(conn)["param_version"] == "p-x"


def test_incomplete_still_stamps(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    calls = {"complete": None}

    def _wsc(complete, elapsed_min=0.0):
        calls["complete"] = complete

    monkeypatch.setattr("scripts.sync_bars_sample.write_sync_complete", _wsc)
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn", lambda: bars_conn(str(db))
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["600000.SH", "600001.SH"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.sync_symbol_bars", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day", lambda: dt.date(2024, 1, 9)
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: 2,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "vendor_fields"})(),
    )
    rc = main(["--end", "2024-01-09", "--max-codes", "1", "--skip-flags"])
    assert rc == 0
    assert calls["complete"] is False
    conn = bars_conn(str(db))
    assert read_hard_freeze_pass_meta(conn)["n"] == 20
