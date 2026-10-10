"""SW classify download: CA-bundle verify (certifi + GeoTrust), timeout, retries."""
from __future__ import annotations

import io
import os

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


def test_sw_ca_bundle_includes_geotrust_intermediate():
    path = fsm._sw_ca_bundle_path()
    assert os.path.isfile(path)
    text = open(path, encoding="utf-8").read()
    assert "BEGIN CERTIFICATE" in text
    assert "GeoTrust G2 TLS CN RSA4096 SHA256 2022 CA1" in text or os.path.isfile(
        fsm._GEO_TRUST_INT_PEM
    )
    # Vendored intermediate must be appended (bundle larger than certifi alone).
    import certifi

    assert os.path.getsize(path) > os.path.getsize(certifi.where())
    vendored = open(fsm._GEO_TRUST_INT_PEM, encoding="utf-8").read()
    assert "BEGIN CERTIFICATE" in vendored
    assert vendored.strip() in text


def test_fetch_latest_rows_uses_ca_bundle_not_verify_false(monkeypatch):
    calls = {}

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["verify"] = kwargs.get("verify")
        calls["timeout"] = kwargs.get("timeout")
        return _ok_resp()

    monkeypatch.setattr(requests, "get", fake_get)
    _stub_excel(monkeypatch)

    rows = fsm.fetch_latest_rows()
    assert calls.get("verify") is not False
    assert isinstance(calls.get("verify"), str)
    assert os.path.isfile(calls["verify"])
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
    assert sleeps == [1, 2]
    assert all(isinstance(k.get("verify"), str) for k in get_kwargs)
    assert all(k.get("verify") is not False for k in get_kwargs)
    assert all(k.get("timeout") == fsm._SW_TIMEOUT_SEC for k in get_kwargs)


def test_download_raises_after_three_failures(monkeypatch):
    def always_fail(url, **kwargs):
        raise requests.exceptions.ReadTimeout("slow")

    monkeypatch.setattr(requests, "get", always_fail)
    import time as time_mod

    monkeypatch.setattr(time_mod, "sleep", lambda *_a, **_k: None)

    with pytest.raises(RuntimeError, match="after 3 attempts"):
        fsm._download_sw_classify_xls()
