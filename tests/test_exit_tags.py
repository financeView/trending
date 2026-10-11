"""Exit-tag params load (Task 0) and later assign/digest tests."""
from pathlib import Path

import pytest

from scripts.metrics.params import load_params

ROOT = Path(__file__).resolve().parents[1]
METRICS_YAML = ROOT / "config" / "metrics" / "a_share_daily.yaml"

_EXIT_TAG_KEYS = (
    "vol_expand_pctile",
    "champ_k",
    "champ_excess",
    "danger_ret_pctile",
    "danger_amt_pctile",
    "tag_rate_cap",
)


def _yaml_without_key(key: str) -> str:
    lines = METRICS_YAML.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith(f"{key}:")) + "\n"


def test_load_params_requires_exit_tag_thresholds(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(_yaml_without_key("vol_expand_pctile"), encoding="utf-8")
    with pytest.raises((KeyError, ValueError)):
        load_params(p)


def test_a_share_daily_exit_tag_thresholds():
    params = load_params(METRICS_YAML)
    assert params.param_version == "p05-v3"
    assert params.exit_tags_enabled is False
    assert params.vol_expand_pctile == 0.90
    assert params.champ_k == 3
    assert params.champ_excess == 0.05
    assert params.danger_ret_pctile == 0.05
    assert params.danger_amt_pctile == 0.95
    assert params.tag_rate_cap == 0.02
