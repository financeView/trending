"""§8.9 named solar fixture suite — CI fails if any required ID is missing."""
from pathlib import Path

import pytest

from tests.fixture_suite import assert_required_ids, run_named_fixture

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "solar"

REQUIRED_SOLAR_IDS = (
    "solar_entry_grain_rain",
    "solar_jump_on_spike",
    "solar_drawdown_no_retreat",
    "solar_early_exit_liqiu",
    "solar_exit_day_liqiu",
    "solar_clamp_high",
    "solar_halt_no_advance",
)


def test_solar_required_ids_present():
    assert_required_ids(FIXTURE_DIR, REQUIRED_SOLAR_IDS)


@pytest.mark.parametrize(
    "path",
    sorted(FIXTURE_DIR.glob("*.json")) if FIXTURE_DIR.is_dir() else [],
    ids=lambda p: p.stem,
)
def test_solar_named_fixture(path: Path):
    run_named_fixture(path)
