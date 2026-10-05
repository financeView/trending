from pathlib import Path

from scripts.sync_bars_sample import codes_from_universe


def test_codes_from_universe_stub():
    root = Path(__file__).resolve().parents[1]
    codes = codes_from_universe(str(root / "config" / "taxonomy" / "universe_stub.yaml"))
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
