from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import requests

import scripts.common.sws_tls as sws_tls
from scripts.common.sws_tls import INTERMEDIATE_CERT, INTERMEDIATE_SHA256, verified_sws_ca_bundle
from scripts import fund_industry

ROOT = Path(__file__).resolve().parents[1]
LEAF_FIXTURE = ROOT / "tests" / "fixtures" / "tls" / "swsresearch_leaf_2026.pem"


def test_module_cli_entrypoint_imports_without_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.run_fund_industry", "--help"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--all-industries" in result.stdout


def test_bundle_preserves_active_roots_and_adds_only_hash_pinned_intermediate():
    base_bundle = Path(requests.certs.where())
    original = base_bundle.read_bytes()

    with verified_sws_ca_bundle(base_bundle) as bundle:
        combined = bundle.read_bytes()
        assert combined.startswith(original)
        assert INTERMEDIATE_CERT.read_bytes().strip() in combined
        assert bundle.exists()
    assert not bundle.exists()

    assert len(INTERMEDIATE_SHA256) == 64


def test_modified_intermediate_fails_closed(tmp_path, monkeypatch):
    tampered = tmp_path / "tampered-intermediate.pem"
    pem = bytearray(INTERMEDIATE_CERT.read_bytes())
    payload_offset = pem.index(b"\n") + 1
    pem[payload_offset] = ord("A") if pem[payload_offset] != ord("A") else ord("B")
    tampered.write_bytes(pem)
    monkeypatch.setattr(sws_tls, "INTERMEDIATE_CERT", tampered)

    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        with sws_tls.verified_sws_ca_bundle(requests.certs.where()):
            pytest.fail("tampered issuer must never enter a TLS bundle")


def test_offline_sw_tls_chain_reaches_existing_digicert_root():
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("OpenSSL CLI is required for the offline certificate path test")

    # Validate the captured public leaf at a fixed point inside its validity window,
    # so this chain regression stays offline and deterministic after the leaf rotates.
    fixed_time = int(datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    with verified_sws_ca_bundle() as bundle:
        result = subprocess.run(
            [
                openssl,
                "verify",
                "-verbose",
                "-show_chain",
                "-no-CApath",
                "-no-CAstore",
                "-attime",
                str(fixed_time),
                "-CAfile",
                str(bundle),
                "-untrusted",
                str(INTERMEDIATE_CERT),
                "-verify_hostname",
                "www.swsresearch.com",
                str(LEAF_FIXTURE),
            ],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DigiCert Global Root G2" in result.stdout
    assert "depth=2" in result.stdout

    untrusted_intermediate = subprocess.run(
        [
            openssl,
            "verify",
            "-no-CApath",
            "-no-CAstore",
            "-attime",
            str(fixed_time),
            "-CAfile",
            str(INTERMEDIATE_CERT),
            "-untrusted",
            str(INTERMEDIATE_CERT),
            "-verify_hostname",
            "www.swsresearch.com",
            str(LEAF_FIXTURE),
        ],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert untrusted_intermediate.returncode != 0
    assert "unable to get issuer certificate" in untrusted_intermediate.stderr


def test_sw_history_download_passes_strict_ephemeral_bundle(monkeypatch):
    captured = {}

    class Response:
        content = b"offline XLS fixture handled by mocked parser"
        url = "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls"
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

    def fake_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        bundle = Path(kwargs["verify"])
        assert bundle.is_file()
        assert b"-----BEGIN CERTIFICATE-----" in bundle.read_bytes()
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: pd.DataFrame(
            {
                "股票代码": ["000001"],
                "计入日期": ["2021-09-01"],
                "行业代码": ["370100"],
                "更新日期": ["2021-09-02"],
            }
        ),
    )

    result = fund_industry.fetch_sw_classification_history()
    assert captured["url"] == Response.url
    assert isinstance(captured["verify"], str)
    assert captured["timeout"] == (10, 60)
    assert captured["allow_redirects"] is False
    assert result.loc[0, "symbol"] == "000001"
    assert result.loc[0, "industry_code"] == "370100"
    assert str(result.loc[0, "start_date"]) == "2021-09-01"
    assert not Path(captured["verify"]).exists()


@pytest.mark.parametrize(
    "location",
    [
        "http://www.swsresearch.com/downgrade.xls",
        "https://attacker.example/steal.xls",
        "https://www.swsresearch.com/same-host.xls",
        "//attacker.example/protocol-relative.xls",
        "https://user@www.swsresearch.com/userinfo.xls",
        "https://www.swsresearch.com:invalid/bad-port.xls",
    ],
)
def test_sw_history_download_never_requests_redirect_target(monkeypatch, location):
    source_url = (
        "https://www.swsresearch.com/swindex/pdf/SwClass2021/"
        "StockClassifyUse_stock.xls"
    )
    requested = []

    class RedirectResponse:
        url = source_url
        status_code = 302
        headers = {"Location": location}

    def fake_get(url, **kwargs):
        requested.append(url)
        assert kwargs["allow_redirects"] is False
        return RedirectResponse()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(
        fund_industry, "_call_with_retry", lambda fn, **_kwargs: fn()
    )

    with pytest.raises(fund_industry.FundIndustryError, match="redirects are disabled"):
        fund_industry.fetch_sw_classification_history()

    assert requested == [source_url]
    assert location not in requested
