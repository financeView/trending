import pytest

from scripts.metrics.params import load_params
from scripts.metrics.rs_raw import compute_rs_raw


def _params():
    return load_params("config/metrics/a_share_daily.yaml")


def test_rs_raw_null_until_252():
    closes = [float(100 + i) for i in range(100)]
    out = compute_rs_raw(closes, _params())
    assert all(v is None for v in out)


def test_rs_raw_weighted_roc_at_end():
    # 253 closes: index 252 can see 252 lookback; constant +1%/bar locks rs_w*
    closes = [100.0]
    for i in range(252):
        closes.append(closes[-1] * 1.01)
    p = _params()
    out = compute_rs_raw(closes, p)
    assert out[-1] is not None
    expected = (
        p.rs_w1 * (1.01**63 - 1)
        + p.rs_w2 * (1.01**126 - 1)
        + p.rs_w3 * (1.01**189 - 1)
        + p.rs_w4 * (1.01**252 - 1)
    )
    assert out[-1] == pytest.approx(expected)
