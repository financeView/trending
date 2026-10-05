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


def test_with_limits_em_failure_exits_zero(monkeypatch):
    class _Conn:
        def close(self):
            return None

    monkeypatch.setattr("scripts.sync_bars_sample.bars_conn", lambda: _Conn())

    def _boom(*_a, **_k):
        raise RuntimeError("em_f51f52: clist 全部 host 失败")

    monkeypatch.setattr("scripts.sync_bars_sample.sync_em_limits_asof", _boom)
    from scripts.sync_bars_sample import main

    rc = main(
        [
            "--skip-ohlc",
            "--skip-flags",
            "--with-limits",
            "--codes",
            "000001.SZ",
            "--end",
            "2024-01-10",
        ]
    )
    assert rc == 0
