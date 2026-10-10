"""SW classify download: scoped TLS verify=False, long timeout, backoff retries."""
from __future__ import annotations

import io

import pandas as pd
import pytest
import requests

from scripts.taxonomy import fetch_sw_members as fsm


def _ok_resp(body: bytes = b"x" * 12_000):
    class Resp:
        status_code = 200

        def __init__(self):
            self.content = body

        def raise_for_status(self):
            return None

    return Resp()


def _stub_excel(monkeypatch):
    df = pd.DataFrame(
        {
            "股票代码": ["000001", "000001", "600000"],
            "计入日期": ["2020-01-01", "2024-01-01", "2024-01-01"],
            "行业代码": ["110101", "110100", "480100"],
            "更新日期": ["2024-01-01", "2024-01-01", "2024-01-01"],
        }
    )

    def fake_read_excel(buf, dtype=None):
        assert isinstance(buf, io.BytesIO) or hasattr(buf, "read")
        return df.copy()

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)


def test_fetch_latest_rows_passes_verify_false_and_long_timeout(monkeypatch):
    calls = {}

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["verify"] = kwargs.get("verify")
        calls["timeout"] = kwargs.get("timeout")
        return _ok_resp()

    monkeypatch.setattr(requests, "get", fake_get)
    _stub_excel(monkeypatch)

    rows = fsm.fetch_latest_rows()
    assert calls.get("verify") is False
    assert calls.get("timeout") == fsm._SW_TIMEOUT_SEC
    assert fsm._SW_TIMEOUT_SEC >= 180
    assert "swsresearch.com" in calls.get("url", "")
    by_ts = {r["ts_code"]: r["industry_code"] for r in rows}
    assert by_ts["000001.SZ"] == "110100"
    assert by_ts["600000.SH"] == "480100"


def test_download_retries_three_times_with_backoff(monkeypatch):
    n = {"i": 0}
    sleeps = []
    get_kwargs = []

    def fake_get(url, **kwargs):
        n["i"] += 1
        get_kwargs.append(dict(kwargs))
        if n["i"] < 3:
            raise requests.exceptions.ReadTimeout("slow")
        return _ok_resp()

    monkeypatch.setattr(requests, "get", fake_get)
    import time as time_mod

    monkeypatch.setattr(time_mod, "sleep", sleeps.append)

    content = fsm._download_sw_classify_xls()
    assert len(content) >= 10_000
    assert n["i"] == fsm._SW_ATTEMPTS == 3
    assert sleeps == [1, 2]  # min(2**0,8)=1, min(2**1,8)=2; no sleep after last
    assert all(k.get("verify") is False for k in get_kwargs)
    assert all(k.get("timeout") == fsm._SW_TIMEOUT_SEC for k in get_kwargs)


def test_download_raises_after_three_failures(monkeypatch):
    def always_fail(url, **kwargs):
        raise requests.exceptions.ReadTimeout("slow")

    monkeypatch.setattr(requests, "get", always_fail)
    import time as time_mod

    monkeypatch.setattr(time_mod, "sleep", lambda *_a, **_k: None)

    with pytest.raises(RuntimeError, match="after 3 attempts"):
        fsm._download_sw_classify_xls()
