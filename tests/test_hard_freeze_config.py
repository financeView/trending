from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
YAML = ROOT / "config" / "metrics" / "a_share_daily.yaml"


def test_hard_freeze_n_knob_present():
    raw = yaml.safe_load(YAML.read_text(encoding="utf-8"))
    assert int(raw["hard_freeze_min_suspend_days"]) == 20
    assert raw["param_version"] == "p05-v3"
