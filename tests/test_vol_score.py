"""Spec C stock VOL_score + basket VOL wire (own-history turnover percentile)."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest

from scripts.common.bars import bars_conn
from scripts.daily_run import replay_metrics_cross_section
from scripts.metrics.vol_score import (
    assign_vol_scores,
    compute_vol_scores,
    turnover_from_bar,
)
from tests.test_daily_run_metrics_wire import (
    SHORT_N,
    _seed_uptrend,
    _short_params,
    _weekdays_ending,
)


def test_today_null_turnover_forces_null_even_if_history_rich():
    series = [0.01] * 80 + [None]
    out = compute_vol_scores(series, vol_hist=252, min_samples=60)
    assert out[-1] is None


def test_min_samples_gate():
    series = [0.01] * 10
    out = compute_vol_scores(series, vol_hist=252, min_samples=60)
    assert all(v is None for v in out)


def test_turnover_null_when_float_mv_nonpositive_or_nonfinite():
    assert turnover_from_bar(1e8, 0.0) is None
    assert turnover_from_bar(1e8, -1.0) is None
    assert turnover_from_bar(1e8, None) is None
    assert turnover_from_bar(None, 1e10) is None
    assert turnover_from_bar(1e8, 1e10) == pytest.approx(1e8 / 1e10)


def test_stock_vol_score_nonnull_on_asof_wire(tmp_path, monkeypatch):
    """≥60 finite turnovers + matching asof date → stock VOL_score is 0..100 int."""
    params = replace(_short_params(), vol_hist=80, vol_score_min_samples=60)
    monkeypatch.setattr("scripts.daily_run.load_metrics_params", lambda: params)
    monkeypatch.setattr(
        "scripts.daily_run.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.daily_run.l2_members_map",
        lambda: {"370100": ["000001.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.stub_l1_members",
        lambda: {"l1_test": ["000001.SZ"]},
    )

    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, 80)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()

    stock_rows, _l2, _l1, _ev = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=params,
        universe=["000001.SZ"],
    )
    assert stock_rows
    vol = stock_rows[0].get("VOL_score")
    assert isinstance(vol, int) and 0 <= vol <= 100


def test_bar_trade_date_str_normalizes_datetime():
    from scripts.daily_run import _bar_trade_date_str

    assert _bar_trade_date_str(date(2024, 1, 10)) == "2024-01-10"
    assert _bar_trade_date_str(datetime(2024, 1, 10, 15, 0)) == "2024-01-10"
    assert _bar_trade_date_str("2024-01-10") == "2024-01-10"
    assert _bar_trade_date_str(None) is None


def _stub_mini_basket_taxonomy(monkeypatch):
    monkeypatch.setattr(
        "scripts.metrics.aggregate.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.daily_run.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.common.universe.l2_members_map",
        lambda: {"370100": ["000001.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.l2_members_map",
        lambda: {"370100": ["000001.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )
    monkeypatch.setattr(
        "scripts.common.universe.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.stub_l1_members",
        lambda: {"l1_test": ["000001.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.stub_l1_members",
        lambda: {"l1_test": ["000001.SZ"]},
    )


def test_basket_vol_null_below_min_samples(tmp_path, monkeypatch):
    """n < vol_score_min_samples → L2/L1 VOL_score stays null."""
    params = replace(_short_params(), vol_score_min_samples=60)
    monkeypatch.setattr("scripts.daily_run.load_metrics_params", lambda: params)
    _stub_mini_basket_taxonomy(monkeypatch)

    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)  # << 60
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()

    _stock, l2_rows, l1_rows, _events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=params,
        universe=["000001.SZ"],
    )
    assert l2_rows, "expected L2 rows from wire fixture"
    assert l1_rows, "expected L1 rows from wire fixture"
    assert all(r.get("VOL_score") is None for r in l2_rows)
    assert all(r.get("VOL_score") is None for r in l1_rows)


def test_basket_vol_matches_compute_vol_scores_on_synth_turnovers(tmp_path, monkeypatch):
    """asof L2/L1 VOL_score equals compute_vol_scores on captured synth turnovers."""
    params = replace(_short_params(), vol_hist=80, vol_score_min_samples=60)
    monkeypatch.setattr("scripts.daily_run.load_metrics_params", lambda: params)
    _stub_mini_basket_taxonomy(monkeypatch)

    D = date(2024, 1, 10)
    td = D.isoformat()
    dates = _weekdays_ending(D, 80)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )

    import scripts.daily_run as dr

    synth_calls: list[list] = []
    real_synth = dr.synthesize_basket_bars

    def spy_synth(member_bars, *, trade_dates):
        out = real_synth(member_bars, trade_dates=trade_dates)
        synth_calls.append(out)
        return out

    monkeypatch.setattr(dr, "synthesize_basket_bars", spy_synth)

    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()

    _stock, l2_rows, l1_rows, _events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=params,
        universe=["000001.SZ"],
    )
    assert l2_rows and l1_rows
    assert len(synth_calls) >= 2  # L2 then L1
    captured = {"370100": synth_calls[0], "l1_test": synth_calls[1]}

    def expected_asof(synth):
        turnovers = [
            turnover_from_bar(b.get("amount"), b.get("float_mv")) for b in synth
        ]
        scores = compute_vol_scores(
            turnovers,
            vol_hist=params.vol_hist,
            min_samples=params.vol_score_min_samples,
        )
        for i, b in enumerate(synth):
            raw = b.get("trade_date")
            bar_td = raw.isoformat()[:10] if hasattr(raw, "isoformat") else str(raw)[:10]
            if bar_td == td:
                return scores[i] if i < len(scores) else None
        return None

    assert l2_rows[0]["VOL_score"] == expected_asof(captured["370100"])
    assert l1_rows[0]["VOL_score"] == expected_asof(captured["l1_test"])
    assert isinstance(l2_rows[0]["VOL_score"], int)
    assert 0 <= l2_rows[0]["VOL_score"] <= 100


def test_assign_vol_does_not_change_rs():
    rows = [
        {"code": "370100", "RS": 77.5, "VOL_score": None},
        {"code": "370200", "RS": 12.0, "VOL_score": None},
    ]
    series = {
        "370100": [
            {"trade_date": f"2024-01-{i:02d}", "amount": 1e8, "float_mv": 1e10}
            for i in range(1, 21)
        ]
        + [{"trade_date": "2024-02-01", "amount": 2e8, "float_mv": 1e10}],
        "370200": [
            {"trade_date": f"2024-01-{i:02d}", "amount": 1e8, "float_mv": 1e10}
            for i in range(1, 21)
        ]
        + [{"trade_date": "2024-02-01", "amount": 5e7, "float_mv": 1e10}],
    }
    before = [r["RS"] for r in rows]
    assign_vol_scores(
        rows,
        series,
        trade_date="2024-02-01",
        vol_hist=40,
        min_samples=10,
        code_key="code",
    )
    assert [r["RS"] for r in rows] == before
    assert all(isinstance(r["VOL_score"], int) for r in rows)
