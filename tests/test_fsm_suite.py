"""§6.4 named FSM fixture suite — CI fails if any required ID is missing."""
from pathlib import Path

import pytest

from tests.fixture_suite import assert_required_ids, run_named_fixture

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "fsm"

REQUIRED_FSM_IDS = (
    "fsm_enter_hyst",
    "fsm_enter_boil",
    "fsm_no_enter_warm",
    "fsm_persist_warm",
    "fsm_exit_warm_to_flat",
    "fsm_exit_hot_to_flat",
    "fsm_exit_boil_to_cool",
    "fsm_crash_boil_to_freeze",
    "fsm_reconfirm",
    "fsm_reentry",
    "fsm_null_in_R",
    "fsm_null_not_R",
    "fsm_fri_mon",
    "fsm_bootstrap",
    "fsm_untradable_freeze",
    "fsm_st_ends_right",
)


def test_fsm_required_ids_present():
    assert_required_ids(FIXTURE_DIR, REQUIRED_FSM_IDS)


@pytest.mark.parametrize(
    "path",
    sorted(FIXTURE_DIR.glob("*.json")) if FIXTURE_DIR.is_dir() else [],
    ids=lambda p: p.stem,
)
def test_fsm_named_fixture(path: Path):
    run_named_fixture(path)
