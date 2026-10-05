# SW Research TLS chain supplement

`digicert_geotrust_g2_tls_cn_rsa4096_sha256_2022_ca1.pem` is a public DigiCert intermediate certificate used only to complete the TLS chain for `www.swsresearch.com`, whose server currently omits it.

- Subject: `CN=GeoTrust G2 TLS CN RSA4096 SHA256 2022 CA1, O=DigiCert, Inc., C=US`
- Issuer: `CN=DigiCert Global Root G2, OU=www.digicert.com, O=DigiCert Inc, C=US`
- Validity: 2022-12-15 through 2032-12-14 UTC
- DER SHA-256: `05dc9edc0fddfa975a1432ef806ec780078b5362ad45af76db15c907630db25d`
- Source: `http://cacerts.digicert.cn/GeoTrustG2TLSCNRSA4096SHA2562022CA1.crt`, the CA Issuers URL advertised in the `www.swsresearch.com` leaf certificate's Authority Information Access extension.

The source endpoint is HTTP, so the downloaded bytes were not trusted merely because they came from that URL. The SHA-256 pin above was checked, and OpenSSL verified the intermediate's signature path through the existing Certifi DigiCert Global Root G2 trust anchor. The offline regression test repeats verification using the captured public leaf certificate, this intermediate as untrusted chain material, the active root bundle, hostname validation, and a fixed instant within the leaf's validity period.

At runtime, the program checks the exact DER fingerprint and appends the intermediate to a mode-0600 temporary copy of the active Requests CA bundle. It never changes system trust, never disables certificate or hostname checks, and does not enable OpenSSL partial-chain trust. Verification must still reach a root already present in the active CA bundle. The temporary bundle is deleted after the request.

## Rotation and expiry

Recheck the live leaf's issuer and Authority Information Access when DigiCert rotates the site certificate, the pinned intermediate approaches expiry, or verification fails. Obtain the replacement from the issuer's published certificate source, record its DER SHA-256, and verify its path to an already trusted root with hostname checking before updating this file, the pin, and the offline chain fixture/test. Never respond to a rotation by disabling TLS verification, adding an unverified certificate as a root, or silently continuing with stale trust material. The current leaf fixture is intentionally historical; the offline test pins its verification time so it remains useful after the leaf expires, while normal live requests always validate the current leaf's validity.
