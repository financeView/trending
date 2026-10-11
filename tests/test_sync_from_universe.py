from pathlib import Path

from scripts.sync_bars_sample import codes_from_universe


def test_codes_from_universe_stub():
    root = Path(__file__).resolve().parents[1]
    codes = codes_from_universe(str(root / "tests" / "fixtures" / "universe_stub.yaml"))
    assert "000001.SZ" in codes
    assert "600519.SH" in codes
    assert len(codes) >= 5


def test_codes_from_universe_drops_quarantine(tmp_path):
    p = tmp_path / "uni.yaml"
    p.write_text(
        "map_version: t\nmembers:\n  - 000001.SZ\n  - 000002.SZ\nquarantine:\n  - 000002.SZ\n",
        encoding="utf-8",
    )
    assert codes_from_universe(str(p)) == ["000001.SZ"]


def test_with_limits_em_failure_exits_zero(tmp_path, monkeypatch):
    """EM limits boom must not kill sync; Spec E passes still need a real bars conn."""
    from scripts.common.bars import bars_conn
    from scripts.sync_bars_sample import main

    db = tmp_path / "b.db"
    called = {"em": 0}

    def _boom(*_a, **_k):
        called["em"] += 1
        raise RuntimeError("em_f51f52: clist 全部 host 失败")

    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn", lambda: bars_conn(str(db))
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["000001.SZ"],
    )
    monkeypatch.setattr("scripts.sync_bars_sample.sync_em_limits_asof", _boom)
    monkeypatch.setattr(
        "scripts.sync_bars_sample.write_sync_complete", lambda *a, **k: None
    )
    from scripts.common.hard_freeze import HardFreezePassConfig

    monkeypatch.setattr(
        "scripts.common.hard_freeze.load_hard_freeze_pass_config",
        lambda path=None: HardFreezePassConfig(
            min_suspend_days=20, param_version="p05-v3"
        ),
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "board_calc_v1"})(),
    )

    rc = main(
        [
            "--skip-ohlc",
            "--skip-flags",
            "--with-limits",
            "--codes",
            "000001.SZ",
            "--end",
            "2024-01-10",
            "--asof",
            "2024-01-10",  # must match --end or with-limits is skipped
        ]
    )
    assert rc == 0
    assert called["em"] == 1
