"""SW classify download uses scoped TLS verify=False (GHA CA chain)."""
from __future__ import annotations

import io

import pandas as pd
import requests

from scripts.taxonomy import fetch_sw_members as fsm


def test_fetch_latest_rows_passes_verify_false(monkeypatch):
    calls = {}

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["verify"] = kwargs.get("verify")

        class Resp:
            status_code = 200
            content = b"x" * 12_000

            def raise_for_status(self):
                return None

        return Resp()

    monkeypatch.setattr(requests, "get", fake_get)

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

    rows = fsm.fetch_latest_rows()
    assert calls.get("verify") is False
    assert "swsresearch.com" in calls.get("url", "")
    by_ts = {r["ts_code"]: r["industry_code"] for r in rows}
    assert by_ts["000001.SZ"] == "110100"
    assert by_ts["600000.SH"] == "480100"
