from scripts.metrics.params import load_params
from scripts.metrics.rs_raw import compute_rs_raw


def _params():
    return load_params("config/metrics/a_share_daily.yaml")


def test_rs_raw_null_until_252():
    closes = [float(100 + i) for i in range(100)]
    out = compute_rs_raw(closes, _params())
    assert all(v is None for v in out)


def test_rs_raw_weighted_roc_at_end():
    # 253 closes: index 252 can see 252 lookback
    closes = [100.0]
    for i in range(252):
        closes.append(closes[-1] * 1.01)
    out = compute_rs_raw(closes, _params())
    assert out[-1] is not None
    # all positive trend → RS_raw > 0
    assert out[-1] > 0
