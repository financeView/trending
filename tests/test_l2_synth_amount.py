"""Paired Σamount / Σfloat_mv on basket synth bars (Spec basket-vol §3.1)."""


def _bar(td, close, *, amount=None, float_mv=1e9, prev_close=None):
    pc = prev_close if prev_close is not None else close
    return {
        "trade_date": td,
        "close_qfq": close,
        "high_qfq": close,
        "low_qfq": close,
        "float_mv": float_mv,
        "amount": amount,
        "is_st": 0,
        "is_suspended": 0,
    }


def test_paired_sum_skips_member_missing_amount_or_mv():
    from datetime import date

    from scripts.metrics.l2_synth import synthesize_basket_bars

    d0, d1 = date(2024, 1, 8), date(2024, 1, 9)
    bars = {
        "A.SZ": [
            _bar("2024-01-08", 10.0, amount=100.0),
            _bar("2024-01-09", 11.0, amount=100.0),
        ],
        "B.SZ": [
            _bar("2024-01-08", 10.0, amount=50.0, float_mv=1e9),
            _bar("2024-01-09", 11.0, amount=50.0, float_mv=None),
        ],
        "C.SZ": [
            _bar("2024-01-08", 10.0, amount=None, float_mv=1e9),
            _bar("2024-01-09", 11.0, amount=None, float_mv=2e9),
        ],
    }
    out = synthesize_basket_bars(bars, trade_dates=[d0, d1])
    assert len(out) == 1
    assert out[0]["amount"] == 100.0
    assert out[0]["float_mv"] == 1e9


def test_no_paired_members_omits_or_nulls_amount_mv():
    from datetime import date

    from scripts.metrics.l2_synth import synthesize_basket_bars

    d0, d1 = date(2024, 1, 8), date(2024, 1, 9)
    bars = {
        "B.SZ": [
            _bar("2024-01-08", 10.0, amount=50.0),
            _bar("2024-01-09", 11.0, amount=50.0, float_mv=None),
        ],
        "C.SZ": [
            _bar("2024-01-08", 10.0, amount=None),
            _bar("2024-01-09", 11.0, amount=None, float_mv=2e9),
        ],
    }
    out = synthesize_basket_bars(bars, trade_dates=[d0, d1])
    assert len(out) == 1
    assert out[0].get("amount") is None
    assert out[0].get("float_mv") is None


def test_price_path_unchanged_when_amounts_added():
    from datetime import date

    from scripts.metrics.l2_synth import synthesize_l2_bars

    d0, d1 = date(2024, 1, 8), date(2024, 1, 9)

    def member_bars(*, with_amount: bool):
        extra = {}
        if with_amount:
            extra = {"amount": 1e8}
        return {
            "A.SZ": [
                {
                    "trade_date": "2024-01-08",
                    "close_qfq": 10.0,
                    "high_qfq": 10.0,
                    "low_qfq": 10.0,
                    "float_mv": 1e9,
                    "is_st": 0,
                    "is_suspended": 0,
                    **extra,
                },
                {
                    "trade_date": "2024-01-09",
                    "close_qfq": 11.0,
                    "high_qfq": 12.0,
                    "low_qfq": 10.5,
                    "float_mv": 1e9,
                    "is_st": 0,
                    "is_suspended": 0,
                    **({"amount": 1.1e8} if with_amount else {}),
                },
            ],
            "B.SZ": [
                {
                    "trade_date": "2024-01-08",
                    "close_qfq": 20.0,
                    "high_qfq": 20.0,
                    "low_qfq": 20.0,
                    "float_mv": 1e9,
                    "is_st": 0,
                    "is_suspended": 0,
                    **extra,
                },
                {
                    "trade_date": "2024-01-09",
                    "close_qfq": 22.0,
                    "high_qfq": 23.0,
                    "low_qfq": 21.0,
                    "float_mv": 1e9,
                    "is_st": 0,
                    "is_suspended": 0,
                    **({"amount": 2.2e8} if with_amount else {}),
                },
            ],
        }

    ref = synthesize_l2_bars(member_bars(with_amount=False), trade_dates=[d0, d1])
    out = synthesize_l2_bars(member_bars(with_amount=True), trade_dates=[d0, d1])
    assert len(ref) == len(out) == 1
    for key in ("close_qfq", "high_qfq", "low_qfq"):
        assert abs(ref[0][key] - out[0][key]) < 1e-9
