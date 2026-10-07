"""C5: L2 same-engine matches single-stock replay on identical twins."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from scripts.common.bars import bars_conn
from scripts.metrics.l2_synth import synthesize_l2_bars
from scripts.metrics.pipeline import replay_from_ohlc
from scripts.metrics.rs_raw import compute_rs_raw
from tests.test_daily_run_metrics_wire import (
    SHORT_N,
    _seed_uptrend,
    _short_params,
    _weekdays_ending,
)


def _assert_opt_approx(actual: Any, expected: Any) -> None:
    """Match None↔None or finite floats via pytest.approx (RS_raw may be null under short hist)."""
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected)


def test_C5_same_engine_on_synthetic(tmp_path, monkeypatch):
    """Two identical OHLC members, equal float_mv → L2 asof T/R/tags/solar == single stock."""
    from scripts.daily_run import _load_symbol_bars, replay_metrics_cross_section

    monkeypatch.setattr(
        "scripts.daily_run.load_metrics_params", lambda: _short_params()
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.common.universe.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )

    D = date(2024, 1, 10)
    # +1 so synth (skips first calendar day) still reaches min_history_temp.
    dates = _weekdays_ending(D, SHORT_N + 1)
    # Inject full calendar = seed weekdays (never rely on holiday-skewed bar-union).
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    _seed_uptrend(conn, "000002.SZ", dates, start_px=20.0)  # different level, same +1.5%/day
    conn.close()

    params = _short_params()
    stock_rows, l2_rows, _l1, events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=params,
        universe=["000001.SZ", "000002.SZ"],
    )
    assert stock_rows
    l2 = next(r for r in l2_rows if r["code"] == "370100")
    assert l2["T"] is not None

    bconn = bars_conn(bars_path)
    stock_bars = _load_symbol_bars(bconn, "000001.SZ", D)
    twin_bars = _load_symbol_bars(bconn, "000002.SZ", D)
    bconn.close()

    synth = synthesize_l2_bars(
        {"000001.SZ": stock_bars, "000002.SZ": twin_bars},
        trade_dates=dates,
    )
    assert synth, "twins with equal returns must synthesize"
    # Chain returns == either twin's day returns (not absolute price levels).
    for i, bar in enumerate(synth):
        td = bar["trade_date"]
        idx = next(j for j, r in enumerate(stock_bars) if r["trade_date"] == td)
        assert idx >= 1
        stock_ret = float(stock_bars[idx]["close_qfq"]) / float(
            stock_bars[idx - 1]["close_qfq"]
        ) - 1.0
        if i == 0:
            synth_ret = float(bar["close_qfq"]) - 1.0
        else:
            synth_ret = float(bar["close_qfq"]) / float(synth[i - 1]["close_qfq"]) - 1.0
        assert abs(synth_ret - stock_ret) < 1e-12

    snaps = replay_from_ohlc(params, synth, min_history=SHORT_N)
    asof = [s for s in snaps if s.get("trade_date") == D.isoformat()]
    assert asof
    expected = asof[-1]

    assert l2["T"] == expected.get("T")
    assert l2["right_side"] == int(bool(expected.get("R")))
    assert l2["tag_warm_to_hot"] == int(bool(expected.get("tag_warm_to_hot")))
    assert l2["tag_warm_to_flat"] == int(bool(expected.get("tag_warm_to_flat")))
    assert l2["solar_term"] == expected.get("solar_term")
    # No L2 signal events
    assert all(e["ts_code"] in ("000001.SZ", "000002.SZ") for e in events)
    assert not any(e["ts_code"] == "370100" for e in events)

    # Twin stock asof vs basket engine: RS_raw + S_temp (not cross-section RS).
    stock_snaps = replay_from_ohlc(params, stock_bars, min_history=SHORT_N)
    stock_asof = [s for s in stock_snaps if s.get("trade_date") == D.isoformat()][-1]
    _assert_opt_approx(stock_asof.get("RS_raw"), expected.get("RS_raw"))
    _assert_opt_approx(stock_asof.get("S_temp"), expected.get("S_temp"))
    _assert_opt_approx(l2.get("S_temp"), expected.get("S_temp"))
    _assert_opt_approx(l2.get("RS_raw"), expected.get("RS_raw"))
    assert expected.get("S_temp") is not None
    assert stock_asof.get("S_temp") is not None
    assert l2.get("S_temp") is not None
    # Chain-equal twins → equal ROC path (recompute; asof often null under SHORT_N < 252).
    stock_rs = compute_rs_raw(
        [float(b["close_qfq"]) for b in stock_bars], params
    )
    synth_rs = compute_rs_raw(
        [float(b["close_qfq"]) for b in synth], params
    )
    assert stock_rs[-1] == synth_rs[-1]
    # Do NOT assert cross-section RS equality


def test_C5_same_engine_on_synthetic_l1(tmp_path, monkeypatch):
    """Identical twin stocks in one L1 closure → L1 asof matches single-stock replay."""
    from scripts.daily_run import _load_symbol_bars, replay_metrics_cross_section
    from scripts.metrics.l2_synth import synthesize_basket_bars

    monkeypatch.setattr(
        "scripts.daily_run.load_metrics_params", lambda: _short_params()
    )
    monkeypatch.setattr(
        "scripts.daily_run.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.common.universe.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )
    monkeypatch.setattr(
        "scripts.common.universe.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )

    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 1)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    _seed_uptrend(conn, "000002.SZ", dates, start_px=20.0)
    conn.close()

    params = _short_params()
    _stock, _l2, l1_rows, events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=params,
        universe=["000001.SZ", "000002.SZ"],
    )
    l1 = next(r for r in l1_rows if r["code"] == "l1_test")
    assert l1["T"] is not None

    bconn = bars_conn(bars_path)
    stock_bars = _load_symbol_bars(bconn, "000001.SZ", D)
    twin_bars = _load_symbol_bars(bconn, "000002.SZ", D)
    bconn.close()
    synth = synthesize_basket_bars(
        {"000001.SZ": stock_bars, "000002.SZ": twin_bars},
        trade_dates=dates,
    )
    snaps = replay_from_ohlc(params, synth, min_history=SHORT_N)
    expected = [s for s in snaps if s.get("trade_date") == D.isoformat()][-1]

    assert l1["T"] == expected.get("T")
    assert l1["right_side"] == int(bool(expected.get("R")))
    assert l1["tag_warm_to_hot"] == int(bool(expected.get("tag_warm_to_hot")))
    assert l1["tag_warm_to_flat"] == int(bool(expected.get("tag_warm_to_flat")))
    assert l1["solar_term"] == expected.get("solar_term")
    assert not any(e.get("ts_code") == "l1_test" for e in events)

    # Twin stock asof vs L1 basket engine: RS_raw + S_temp (not cross-section RS).
    stock_snaps = replay_from_ohlc(params, stock_bars, min_history=SHORT_N)
    stock_asof = [s for s in stock_snaps if s.get("trade_date") == D.isoformat()][-1]
    _assert_opt_approx(stock_asof.get("RS_raw"), expected.get("RS_raw"))
    _assert_opt_approx(stock_asof.get("S_temp"), expected.get("S_temp"))
    _assert_opt_approx(l1.get("S_temp"), expected.get("S_temp"))
    _assert_opt_approx(l1.get("RS_raw"), expected.get("RS_raw"))
    assert expected.get("S_temp") is not None
    assert stock_asof.get("S_temp") is not None
    assert l1.get("S_temp") is not None
    stock_rs = compute_rs_raw(
        [float(b["close_qfq"]) for b in stock_bars], params
    )
    synth_rs = compute_rs_raw(
        [float(b["close_qfq"]) for b in synth], params
    )
    assert stock_rs[-1] == synth_rs[-1]
    # Do NOT assert cross-section RS equality
