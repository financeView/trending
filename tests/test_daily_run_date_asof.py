"""--date is replay start; session_asof is latest_trade_day / --asof."""
from datetime import date

import pytest

from scripts.common import calendar as cal
from scripts.daily_run import resolve_session


@pytest.fixture(autouse=True)
def _cal():
    cal.clear_trade_date_cache()
    cal.load_trade_dates_from_list(
        [
            "2026-09-28",
            "2026-09-29",
            "2026-09-30",
            "2026-10-08",
            "2026-10-09",
        ]
    )
    yield
    cal.clear_trade_date_cache()


ASOF = date(2026, 10, 9)


def test_only_date_keeps_asof_separate():
    asof, queue = resolve_session("2026-09-30", True, "", ASOF)
    assert asof == ASOF
    assert queue == [date(2026, 9, 30)]


def test_date_without_only_date_walks_to_asof():
    asof, queue = resolve_session("2026-09-30", False, "", ASOF)
    assert asof == ASOF
    assert queue[0] == date(2026, 9, 30)
    assert queue[-1] == ASOF
    assert date(2026, 10, 8) in queue


def test_only_date_without_date_errors():
    with pytest.raises(ValueError, match="only-date"):
        resolve_session("", True, "", ASOF)


def test_date_after_asof_errors():
    with pytest.raises(ValueError, match="asof"):
        resolve_session("2026-10-10", False, "", ASOF)


def test_empty_date_no_queue_override():
    asof, queue = resolve_session("", False, "", ASOF)
    assert asof == ASOF
    assert queue is None


def test_explicit_asof_overrides_asof_day():
    asof, queue = resolve_session("2026-09-30", True, "2026-10-08", ASOF)
    assert asof == date(2026, 10, 8)
    assert queue == [date(2026, 9, 30)]
