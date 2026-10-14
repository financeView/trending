"""Vendor call hard timeout — fail the attempt, do not quarantine."""
import time

import pytest

from scripts.common.http import call_with_retry


def test_call_with_retry_hard_timeout_raises_once():
    def _hang():
        time.sleep(5)
        return "ok"

    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="exceeded|Timeout|attempts"):
        call_with_retry(
            _hang,
            attempts=3,
            backoffs=(0, 0),
            desc="hang_probe",
            call_timeout_sec=0.2,
        )
    elapsed = time.monotonic() - t0
    # Timeout must not retry (would stack orphans); one 0.2s attempt only.
    assert elapsed < 1.5


def test_call_with_retry_success_within_timeout():
    assert (
        call_with_retry(lambda: 42, attempts=1, call_timeout_sec=5.0, desc="ok") == 42
    )


def test_call_with_retry_no_retry_on_decode_error():
    n = {"c": 0}

    def _boom():
        n["c"] += 1
        raise RuntimeError("sina_raw_sz000003: No value to decode")

    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="No value to decode"):
        call_with_retry(
            _boom, attempts=3, backoffs=(5, 20, 60), desc="dead", call_timeout_sec=5.0
        )
    assert n["c"] == 1
    assert time.monotonic() - t0 < 1.0
