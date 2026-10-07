"""L1 daily_run wire: no aggregate_l1; skip-day NULL; tag ≠ member OR."""
from __future__ import annotations

from datetime import date

from scripts.common.bars import bars_conn
from scripts.daily_run import _basket_asof_row, replay_metrics_cross_section
from tests.test_daily_run_metrics_wire import (
    SHORT_N,
    _seed_uptrend,
    _short_params,
    _weekdays_ending,
)


def _stub_l1_taxonomy(monkeypatch):
    monkeypatch.setattr(
        "scripts.daily_run.load_metrics_params", lambda: _short_params()
    )
    monkeypatch.setattr(
        "scripts.daily_run.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    for mod in (
        "scripts.common.universe.l2_members_map",
        "scripts.daily_run.l2_members_map",
        "scripts.metrics.aggregate.l2_members_map",
    ):
        monkeypatch.setattr(mod, lambda: {"370100": ["000001.SZ"]})
    monkeypatch.setattr(
        "scripts.metrics.aggregate.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )
    monkeypatch.setattr(
        "scripts.common.universe.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )


def test_l1_skip_day_null_engine_fields():
    stock_rows = [
        {
            "ts_code": "A.SZ",
            "l1_id": "wrong",
            "tag_warm_to_hot": 1,
            "amount": 1e8,
            "hard_frozen": 0,
            "_is_suspended": False,
        },
    ]
    row = _basket_asof_row(
        "l1_test",
        ["A.SZ"],
        stock_rows,
        None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert row["T"] is None and row["right_side"] is None
    assert row["tag_warm_to_hot"] is None
    assert row["warm_to_hot_member_count"] == 1
    assert row["members_tradable"] == 1


def test_l1_tag_not_or_of_members():
    cool_snap = {
        "T": "凉",
        "R": False,
        "tag_warm_to_hot": False,
        "tag_warm_to_flat": False,
        "solar_term": None,
    }
    stock_rows = [
        {"ts_code": "A.SZ", "tag_warm_to_hot": 0, "amount": 1e8},
        {"ts_code": "B.SZ", "tag_warm_to_hot": 1, "amount": 2e8},
    ]
    row = _basket_asof_row(
        "l1_test",
        ["A.SZ", "B.SZ"],
        stock_rows,
        cool_snap,
        trade_date="2024-01-10",
        members_total=2,
    )
    assert row["tag_warm_to_hot"] == 0
    assert row["warm_to_hot_member_count"] == 1


def test_l1_wire_does_not_call_aggregate_l1(tmp_path, monkeypatch):
    from scripts import daily_run as dr

    def boom(*a, **k):
        raise AssertionError("aggregate_l1 must not be used for L1 write path")

    monkeypatch.setattr(dr, "aggregate_l1", boom)
    _stub_l1_taxonomy(monkeypatch)
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()
    _s, _l2, l1_rows, events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ"],
    )
    assert any(r["code"] == "l1_test" for r in l1_rows)
    assert not any(e.get("ts_code") == "l1_test" for e in events)


def test_l1_synth_uses_member_closure_stock_bars_not_daily_l2(tmp_path, monkeypatch):
    """Spec §7.4 runtime: synth keys == closure; no daily_l2 price feed."""
    from scripts import daily_run as dr
    from scripts.metrics.aggregate import member_closure

    _stub_l1_taxonomy(monkeypatch)
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()

    captured = {}
    real_synth = dr.synthesize_basket_bars

    def spy_synth(member_bars, *, trade_dates):
        captured["keys"] = sorted(member_bars.keys())
        captured["dates"] = list(trade_dates)
        for ts, rows in member_bars.items():
            assert rows, ts
            assert "close_qfq" in rows[0]
            assert "code" not in rows[0]  # stock bars, not daily_l2 rows
        return real_synth(member_bars, trade_dates=trade_dates)

    monkeypatch.setattr(dr, "synthesize_basket_bars", spy_synth)
    # if still imported as synthesize_l2_bars alias in module, patch that too
    if hasattr(dr, "synthesize_l2_bars"):
        monkeypatch.setattr(dr, "synthesize_l2_bars", spy_synth)

    _s, _l2, l1_rows, _e = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ"],
    )
    assert any(r["code"] == "l1_test" for r in l1_rows)
    expected = sorted(member_closure(["370100"], {"370100": ["000001.SZ"]}))
    assert captured["keys"] == expected


def test_l1_helper_members_tradable_zero_still_has_keys():
    row = _basket_asof_row(
        "l1_test",
        ["A.SZ"],
        [
            {
                "ts_code": "A.SZ",
                "tag_warm_to_hot": 0,
                "amount": None,
                "hard_frozen": True,
                "_is_suspended": False,
            }
        ],
        None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert row["members_tradable"] == 0
    assert row["code"] == "l1_test"
    assert "T" in row and row["T"] is None


def test_l1_wire_keeps_row_when_members_tradable_zero(tmp_path, monkeypatch):
    """Ban production `if members_tradable` filter — assert on wire return list."""
    from scripts import daily_run as dr

    _stub_l1_taxonomy(monkeypatch)
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()

    seen = {}
    real_basket = dr._basket_asof_row

    def tracking_basket(code, members, stock_rows, snap, **kw):
        frozen = []
        for r in stock_rows:
            rr = dict(r)
            if rr.get("ts_code") in set(members):
                rr["hard_frozen"] = True
            frozen.append(rr)
        out = real_basket(code, members, frozen, snap, **kw)
        if code == "l1_test":
            seen["row"] = out
        return out

    monkeypatch.setattr(dr, "_basket_asof_row", tracking_basket)
    monkeypatch.setattr(dr, "_l2_asof_row", tracking_basket)
    _s, _l2, l1_rows, _e = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ"],
    )
    assert any(r["code"] == "l1_test" for r in l1_rows), (
        "YAML closure non-empty must keep L1 row even when members_tradable=0"
    )
    assert seen["row"]["members_tradable"] == 0
