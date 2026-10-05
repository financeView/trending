"""Strict TLS trust-bundle support for the SW Research public XLS endpoint.

The SW server currently omits its DigiCert intermediate certificate. This module
adds that pinned intermediate as chain material to the active Requests CA bundle;
it does not disable verification or introduce a new trust anchor.
"""
from __future__ import annotations

import hashlib
import os
import re
import ssl
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

INTERMEDIATE_CERT = (
    Path(__file__).resolve().parents[2]
    / "certs"
    / "digicert_geotrust_g2_tls_cn_rsa4096_sha256_2022_ca1.pem"
)
INTERMEDIATE_SHA256 = "05dc9edc0fddfa975a1432ef806ec780078b5362ad45af76db15c907630db25d"
_PEM_CERT_RE = re.compile(
    rb"-----BEGIN CERTIFICATE-----\s+.*?\s+-----END CERTIFICATE-----",
    re.DOTALL,
)


def _active_ca_bundle(base_bundle: str | Path | None) -> Path:
    """Resolve Requests' active CA file without modifying process trust settings."""
    if base_bundle is not None:
        return Path(base_bundle).expanduser()

    configured = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE")
    if configured:
        return Path(configured).expanduser()

    import requests

    return Path(requests.certs.where())


def _validated_intermediate() -> bytes:
    pem = INTERMEDIATE_CERT.read_bytes()
    certificates = _PEM_CERT_RE.findall(pem)
    if len(certificates) != 1:
        raise RuntimeError(f"expected exactly one PEM certificate in {INTERMEDIATE_CERT}")
    try:
        der = ssl.PEM_cert_to_DER_cert(certificates[0].decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"invalid pinned SW intermediate certificate: {exc}") from exc
    digest = hashlib.sha256(der).hexdigest()
    if digest != INTERMEDIATE_SHA256:
        raise RuntimeError(
            "pinned SW intermediate certificate SHA-256 mismatch: "
            f"expected {INTERMEDIATE_SHA256}, got {digest}"
        )
    return certificates[0] + b"\n"


@contextmanager
def verified_sws_ca_bundle(
    base_bundle: str | Path | None = None,
) -> Iterator[Path]:
    """Yield an ephemeral PEM bundle containing active roots plus the pinned issuer.

    OpenSSL still builds the certificate path to an existing trusted root in the
    original bundle. The temporary bundle is mode 0600 and is removed on exit.
    """
    roots_path = _active_ca_bundle(base_bundle)
    if not roots_path.is_file():
        raise ValueError(
            "the active Requests CA bundle must be a readable PEM file; "
            f"got {roots_path}"
        )
    try:
        roots = roots_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read active Requests CA bundle {roots_path}: {exc}") from exc
    if b"-----BEGIN CERTIFICATE-----" not in roots:
        raise ValueError(f"active Requests CA bundle contains no PEM certificates: {roots_path}")

    intermediate = _validated_intermediate()
    separator = b"" if roots.endswith(b"\n") else b"\n"
    bundle_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="sws-ca-", suffix=".pem", delete=False) as handle:
            bundle_path = Path(handle.name)
            handle.write(roots)
            handle.write(separator)
            handle.write(intermediate)
        yield bundle_path
    finally:
        if bundle_path is not None:
            bundle_path.unlink(missing_ok=True)
