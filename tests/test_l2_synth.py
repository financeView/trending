"""Tests for pure L2 OHLC synthesis (float_mv chain returns)."""


def test_synth_chain_two_names_known_returns():
    from datetime import date

    from scripts.metrics.l2_synth import synthesize_l2_bars

    d0, d1 = date(2024, 1, 8), date(2024, 1, 9)
    bars = {
        "A.SZ": [
            {
                "trade_date": "2024-01-08",
                "close_qfq": 10.0,
                "high_qfq": 10.0,
                "low_qfq": 10.0,
                "float_mv": 1e9,
                "is_st": 0,
                "is_suspended": 0,
            },
            {
                "trade_date": "2024-01-09",
                "close_qfq": 11.0,
                "high_qfq": 12.0,
                "low_qfq": 10.5,
                "float_mv": 1e9,
                "is_st": 0,
                "is_suspended": 0,
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
            },
            {
                "trade_date": "2024-01-09",
                "close_qfq": 22.0,
                "high_qfq": 23.0,
                "low_qfq": 21.0,
                "float_mv": 1e9,
                "is_st": 0,
                "is_suspended": 0,
            },
        ],
    }
    out = synthesize_l2_bars(bars, trade_dates=[d0, d1])
    # d0 has no prev in trade_dates → omit; d1 r=0.10 → P=1.10
    assert len(out) == 1
    assert out[0]["trade_date"] == "2024-01-09"
    assert abs(out[0]["close_qfq"] - 1.10) < 1e-9


def test_synth_omits_day_when_calendar_prev_close_missing():
    from datetime import date

    from scripts.metrics.l2_synth import synthesize_l2_bars

    d0, d1, d2 = date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10)

    def bar(td, c):
        return {
            "trade_date": td,
            "close_qfq": c,
            "high_qfq": c,
            "low_qfq": c,
            "float_mv": 1e9,
            "is_st": 0,
            "is_suspended": 0,
        }

    # bars only on d0 and d2 — d1 is a trade day with no row
    bars = {"A.SZ": [bar("2024-01-08", 10.0), bar("2024-01-10", 12.0)]}
    out = synthesize_l2_bars(bars, trade_dates=[d0, d1, d2])
    # d2 prev=d1, no close on d1 → R empty → omit d2
    # Wrong bar-union trade_dates=[d0,d2] would use prev=d0 and emit P=1.2 — forbidden
    assert out == []


def test_synth_skips_st_day_and_chains_p_prev():
    from datetime import date

    from scripts.metrics.l2_synth import synthesize_l2_bars

    d0, d1, d2, d3 = (
        date(2024, 1, 8),
        date(2024, 1, 9),
        date(2024, 1, 10),
        date(2024, 1, 11),
    )

    def bar(td, c, *, st=0):
        return {
            "trade_date": td,
            "close_qfq": c,
            "high_qfq": c,
            "low_qfq": c,
            "float_mv": 1e9,
            "is_st": st,
            "is_suspended": 0,
        }

    # d0→d1: +10% → first P=1.1; d2 all ST → omit; d3: +10% vs d2 close → P=1.1*1.1
    bars = {
        "A.SZ": [
            bar("2024-01-08", 10.0),
            bar("2024-01-09", 11.0),
            bar("2024-01-10", 11.0, st=1),
            bar("2024-01-11", 12.1),  # 12.1/11 - 1 = 0.1; chained P=1.21
        ],
    }
    out = synthesize_l2_bars(bars, trade_dates=[d0, d1, d2, d3])
    assert [r["trade_date"] for r in out] == ["2024-01-09", "2024-01-11"]
    assert abs(out[0]["close_qfq"] - 1.10) < 1e-9
    assert abs(out[1]["close_qfq"] - 1.21) < 1e-9  # not 1.10 (would be wrong first-P reset)
