from pathlib import Path

from scripts.sync_bars_sample import codes_from_universe


def test_codes_from_universe_stub():
    root = Path(__file__).resolve().parents[1]
    codes = codes_from_universe(str(root / "config" / "taxonomy" / "universe_stub.yaml"))
    assert "000001.SZ" in codes
    assert "600519.SH" in codes
    assert len(codes) >= 5
