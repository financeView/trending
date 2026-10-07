"""C5: L2 same-engine matches single-stock replay on identical twins."""
from __future__ import annotations

from datetime import date

from scripts.common.bars import bars_conn
from scripts.metrics.pipeline import replay_from_ohlc
from tests.test_daily_run_metrics_wire import (
    SHORT_N,
    _seed_uptrend,
    _short_params,
    _weekdays_ending,
)


def test_C5_same_engine_on_synthetic(tmp_path, monkeypatch):
    """Two identical OHLC members, equal float_mv → L2 asof T/R/tags/solar == single stock."""
    from scripts.daily_run import replay_metrics_cross_section

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
    _seed_uptrend(conn, "000002.SZ", dates, start_px=10.0)
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

    from scripts.daily_run import _load_symbol_bars

    bconn = bars_conn(bars_path)
    stock_bars = _load_symbol_bars(bconn, "000001.SZ", D)
    bconn.close()
    # Synth omits the first calendar day (no prev); align stock history length.
    snaps = replay_from_ohlc(params, stock_bars[1:], min_history=SHORT_N)
    asof = [s for s in snaps if s.get("trade_date") == D.isoformat()]
    assert asof
    single = asof[-1]

    assert l2["T"] == single.get("T")
    assert l2["right_side"] == int(bool(single.get("R")))
    assert l2["tag_warm_to_hot"] == int(bool(single.get("tag_warm_to_hot")))
    assert l2["tag_warm_to_flat"] == int(bool(single.get("tag_warm_to_flat")))
    assert l2["solar_term"] == single.get("solar_term")
    # No L2 signal events
    assert all(e["ts_code"] in ("000001.SZ", "000002.SZ") for e in events)
    assert not any(e["ts_code"] == "370100" for e in events)
