"""Exit-tag params load (Task 0) and later assign/digest tests."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.common import db as dbmod
from scripts.metrics.exit_tags import (
    TAG_DISPLAY,
    TAG_ORDER,
    assign_exit_tags,
    daily_returns,
    format_tags_display,
    tags_to_sql,
)
from scripts.metrics.params import load_params
from scripts.metrics.percentile import scores_0_100
from scripts.metrics.pipeline import replay_from_ohlc
from tests.test_daily_run_metrics_wire import SHORT_N, _short_params

ROOT = Path(__file__).resolve().parents[1]
METRICS_YAML = ROOT / "config" / "metrics" / "a_share_daily.yaml"

_EXIT_TAG_KEYS = (
    "vol_expand_pctile",
    "champ_k",
    "champ_excess",
    "danger_ret_pctile",
    "danger_amt_pctile",
    "tag_rate_cap",
)


def _yaml_without_key(key: str) -> str:
    lines = METRICS_YAML.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith(f"{key}:")) + "\n"


def test_load_params_requires_exit_tag_thresholds(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(_yaml_without_key("vol_expand_pctile"), encoding="utf-8")
    with pytest.raises((KeyError, ValueError)):
        load_params(p)


def _uptrend_ohlc(n: int) -> list[dict]:
    start = date(2024, 1, 2)
    out: list[dict] = []
    for i in range(n):
        close = 10.0 * (1.015**i)
        d = start + timedelta(days=i)
        out.append(
            {
                "trade_date": d.isoformat(),
                "close_qfq": close,
                "high_qfq": close * 1.02,
                "low_qfq": close * 0.99,
                "open_qfq": close * 0.995,
                "is_st": 0,
                "is_suspended": 0,
            }
        )
    return out


def test_replay_from_ohlc_snap_includes_sigma_pctile():
    """Task 2: replay snaps expose sigma_pctile for vol_expand tagging."""
    params = _short_params()
    min_hist = SHORT_N
    records = _uptrend_ohlc(min_hist + 15)
    snaps = replay_from_ohlc(params, records, min_history=min_hist)
    assert snaps
    asof = snaps[-1]
    assert "sigma_pctile" in asof
    sp = asof.get("sigma_pctile")
    assert sp is not None
    assert math.isfinite(float(sp))


def test_a_share_daily_exit_tag_thresholds():
    params = load_params(METRICS_YAML)
    assert params.param_version == "p05-v5"
    assert params.exit_tags_enabled is True
    assert params.vol_expand_pctile == 0.90
    assert params.champ_k == 3
    assert params.champ_excess == 0.05
    assert params.danger_ret_pctile == 0.05
    assert params.danger_amt_pctile == 0.95
    assert params.tag_rate_cap == 0.02


def test_daily_stock_tags_column_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    conn = dbmod.get_conn(str(db))
    dbmod.init_schema(conn)
    dbmod.upsert_daily_stock(
        conn,
        [
            {
                "trade_date": "2024-01-02",
                "ts_code": "000001.SZ",
                "tags": '["vol_expand"]',
            }
        ],
    )
    row = conn.execute(
        "SELECT tags FROM daily_stock WHERE ts_code=?", ("000001.SZ",)
    ).fetchone()
    assert row[0] == '["vol_expand"]'
    conn.close()


def test_daily_l2_tags_column_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    conn = dbmod.get_conn(str(db))
    dbmod.init_schema(conn)
    dbmod.upsert_daily_l2(
        conn,
        [
            {
                "trade_date": "2024-01-02",
                "code": "801780",
                "tags": '["vol_expand"]',
            }
        ],
    )
    row = conn.execute(
        "SELECT tags FROM daily_l2 WHERE code=?", ("801780",)
    ).fetchone()
    assert row[0] == '["vol_expand"]'
    conn.close()


# --- Task 3: pure assign_exit_tags goldens ---

ASOF = "2024-02-01"


def _params(**overrides):
    base = load_params(METRICS_YAML)
    return replace(base, exit_tags_enabled=True, **overrides)


def _bar(td: str, close, *, amount=100.0):
    return {"trade_date": td, "close_qfq": close, "amount": amount}


def _dates(n: int, end: str = ASOF) -> list[str]:
    """n weekdays ending at end (inclusive), ISO strings."""
    from datetime import date, timedelta

    d = date.fromisoformat(end)
    out: list[str] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


def _closes_to_bars(closes, *, amounts=None, dates=None):
    n = len(closes)
    dts = dates or _dates(n)
    amts = amounts if amounts is not None else [100.0] * n
    return [_bar(dts[i], closes[i], amount=amts[i]) for i in range(n)]


def _stock_row(ts_code: str, **kw):
    row = {
        "trade_date": ASOF,
        "ts_code": ts_code,
        "right_side": 0,
        "solar_term": None,
        "_sigma_pctile": None,
        "T": "热",
        "RS": 50,
        "RS_raw": 0.5,
        "VOL_score": 40,
        "hard_frozen": False,
        "_is_suspended": False,
        "tags": None,
    }
    row.update(kw)
    return row


def _l2_row(code: str, **kw):
    row = {
        "trade_date": ASOF,
        "code": code,
        "right_side": 0,
        "solar_term": None,
        "_sigma_pctile": None,
        "T": "热",
        "RS": 50,
        "RS_raw": 0.5,
        "VOL_score": None,
        "tags": None,
    }
    row.update(kw)
    return row


def test_format_and_sql_helpers():
    assert TAG_ORDER == ("vol_expand", "champagne", "danger")
    assert TAG_DISPLAY["vol_expand"] == "波动率放大"
    assert format_tags_display(["danger", "vol_expand"]) == "波动率放大、危险信号"
    assert format_tags_display([]) == ""
    assert tags_to_sql(["danger", "vol_expand"]) == '["vol_expand", "danger"]'


def test_flag_off_all_empty_tags():
    params = _params()
    params = replace(params, exit_tags_enabled=False)
    stocks = [
        _stock_row(
            "A.SZ",
            right_side=1,
            solar_term="大暑",
            _sigma_pctile=0.99,
        )
    ]
    l2 = [_l2_row("L2A", right_side=1, solar_term="大暑", _sigma_pctile=0.99)]
    l1 = [_l2_row("L1A")]
    bars = {"A.SZ": _closes_to_bars([10.0, 11.0, 12.0, 13.0])}
    meta = assign_exit_tags(
        stocks,
        l2,
        l1,
        params=params,
        bar_cache=bars,
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert stocks[0]["tags"] == []
    assert l2[0]["tags"] == []
    assert l1[0]["tags"] == []
    assert meta["stock"] == 0.0
    assert meta["l2"] == 0.0
    assert meta["l1"] == 0.0


def test_vol_expand_golden():
    params = _params()
    stocks = [
        _stock_row(
            "A.SZ",
            right_side=1,
            solar_term="大暑",
            _sigma_pctile=0.95,
        )
    ]
    assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache={"A.SZ": _closes_to_bars([10.0, 10.1])},
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert stocks[0]["tags"] == ["vol_expand"]

    stocks2 = [
        _stock_row(
            "B.SZ",
            right_side=1,
            solar_term="谷雨",
            _sigma_pctile=0.99,
        )
    ]
    assign_exit_tags(
        stocks2,
        [],
        [],
        params=params,
        bar_cache={"B.SZ": _closes_to_bars([10.0, 10.1])},
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert "vol_expand" not in stocks2[0]["tags"]


def test_champagne_breaks_on_uncomputable_day():
    """champ_k=3 but middle day close None → no champagne (no lookback pad)."""
    params = _params(champ_k=3, champ_excess=0.01)
    dts = _dates(4)
    # closes: peer flat; target beats on days with finite ret — but middle close None
    target_closes = [10.0, 11.0, None, 12.0]
    peer_closes = [10.0, 10.0, 10.0, 10.0]
    stocks = [
        _stock_row("T.SZ", RS_raw=1.0),
        _stock_row("P.SZ", RS_raw=0.5),
    ]
    bar_cache = {
        "T.SZ": _closes_to_bars(target_closes, dates=dts),
        "P.SZ": _closes_to_bars(peer_closes, dates=dts),
    }
    assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache=bar_cache,
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert "champagne" not in stocks[0]["tags"]


def test_champagne_short_spine_no_tag():
    params = _params(champ_k=3, champ_excess=0.01)
    dts = _dates(2)
    stocks = [
        _stock_row("T.SZ", RS_raw=1.0),
        _stock_row("P.SZ", RS_raw=0.5),
    ]
    bar_cache = {
        "T.SZ": _closes_to_bars([10.0, 12.0], dates=dts),
        "P.SZ": _closes_to_bars([10.0, 10.1], dates=dts),
    }
    assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache=bar_cache,
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert "champagne" not in stocks[0]["tags"]


def test_champagne_fails_when_day_not_above_median():
    params = _params(champ_k=3, champ_excess=0.01)
    dts = _dates(4)
    # Target underperforms peer on last day
    stocks = [
        _stock_row("T.SZ", RS_raw=1.0),
        _stock_row("P.SZ", RS_raw=0.5),
    ]
    bar_cache = {
        "T.SZ": _closes_to_bars([10.0, 11.0, 12.0, 12.1], dates=dts),
        "P.SZ": _closes_to_bars([10.0, 10.5, 11.0, 12.0], dates=dts),
    }
    assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache=bar_cache,
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert "champagne" not in stocks[0]["tags"]


def test_champagne_fails_when_excess_below_cap():
    params = _params(champ_k=3, champ_excess=1.0)  # unreachable excess
    dts = _dates(4)
    stocks = [
        _stock_row("T.SZ", RS_raw=1.0),
        _stock_row("P.SZ", RS_raw=0.5),
    ]
    # Target beats peer each day but sum(excess) << 1.0
    bar_cache = {
        "T.SZ": _closes_to_bars([10.0, 10.2, 10.4, 10.6], dates=dts),
        "P.SZ": _closes_to_bars([10.0, 10.1, 10.2, 10.3], dates=dts),
    }
    assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache=bar_cache,
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert "champagne" not in stocks[0]["tags"]


def test_champagne_asof_peer_frozen():
    """Ineligible-asof name with huge hist rets must not enter median universe."""
    params = _params(champ_k=3, champ_excess=0.05)
    dts = _dates(4)
    stocks = [
        _stock_row("T.SZ", RS_raw=1.0),
        _stock_row("P.SZ", RS_raw=0.5),
        # quarantined → not in asof peer set
        _stock_row("X.SZ", RS_raw=0.9),
    ]
    # X rockets every day; if wrongly included, T cannot beat median
    bar_cache = {
        "T.SZ": _closes_to_bars([10.0, 11.0, 12.1, 13.3], dates=dts),
        "P.SZ": _closes_to_bars([10.0, 10.2, 10.4, 10.6], dates=dts),
        "X.SZ": _closes_to_bars([10.0, 20.0, 40.0, 80.0], dates=dts),
    }
    assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache=bar_cache,
        l2_synth_by_code={},
        quarantine={"X.SZ"},
        trade_date=ASOF,
    )
    assert "champagne" in stocks[0]["tags"]


def test_danger_uses_window_not_full_spine_rank():
    """Full-spine rank would tag danger; window-then-rank must not."""
    params = _params(
        vol_hist=5,
        danger_ret_pctile=0.05,
        danger_amt_pctile=0.95,
    )
    n = 25
    dts = _dates(n)
    closes = [100.0]
    for i in range(1, n):
        closes.append(closes[-1] * 1.01)
    # One worse day inside the window (index n-3); today 2nd-worst globally
    # so full-spine p_ret ≤ 0.05, but window p_ret = 0.25 > 0.05
    worse_i = n - 3
    closes[worse_i] = closes[worse_i - 1] * (1.0 - 0.50)
    # rebuild path after worse day back up then mild down today
    for j in range(worse_i + 1, n - 1):
        closes[j] = closes[j - 1] * 1.01
    closes[n - 1] = closes[n - 2] * (1.0 - 0.20)

    amounts = [10.0] * n
    amounts[n - 1] = 1e9  # unique max amount → p_amt = 1 both ways

    rets = daily_returns(closes)
    t = n - 1
    # Forbidden full-spine path would tag
    full_scores = scores_0_100(rets)
    p_ret_full = full_scores[t] / 100.0
    assert p_ret_full <= params.danger_ret_pctile
    amt_scores_full = scores_0_100(amounts)
    assert amt_scores_full[t] / 100.0 >= params.danger_amt_pctile

    stocks = [_stock_row("D.SZ")]
    assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache={"D.SZ": _closes_to_bars(closes, amounts=amounts, dates=dts)},
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert "danger" not in stocks[0]["tags"]


def test_danger_stock_golden_and_l2_never_danger():
    params = _params(vol_hist=5, danger_ret_pctile=0.05, danger_amt_pctile=0.95)
    n = 6
    dts = _dates(n)
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 104.0 * (1.0 - 0.30)]
    amounts = [10.0, 10.0, 10.0, 10.0, 10.0, 1e9]
    stocks = [_stock_row("D.SZ")]
    l2 = [
        _l2_row(
            "L2D",
            right_side=1,
            solar_term="大暑",
            _sigma_pctile=0.99,
        )
    ]
    synth = {"L2D": _closes_to_bars(closes, amounts=amounts, dates=dts)}
    assign_exit_tags(
        stocks,
        l2,
        [],
        params=params,
        bar_cache={"D.SZ": _closes_to_bars(closes, amounts=amounts, dates=dts)},
        l2_synth_by_code=synth,
        trade_date=ASOF,
        enable_l2_danger=False,
    )
    assert "danger" in stocks[0]["tags"]
    assert "danger" not in l2[0]["tags"]
    # L2 still may get vol_expand
    assert "vol_expand" in l2[0]["tags"]


def test_l2_danger_enabled_vs_disabled():
    """Extreme down-day + high amount vs own hist → danger only when flag on; L1 []."""
    params = _params(vol_hist=5, danger_ret_pctile=0.05, danger_amt_pctile=0.95)
    n = 6
    dts = _dates(n)
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 104.0 * (1.0 - 0.30)]
    amounts = [10.0, 10.0, 10.0, 10.0, 10.0, 1e9]
    synth = {"L2D": _closes_to_bars(closes, amounts=amounts, dates=dts)}

    l2_off = [_l2_row("L2D")]
    l1_off = [_l2_row("L1D")]
    assign_exit_tags(
        [],
        l2_off,
        l1_off,
        params=params,
        bar_cache={},
        l2_synth_by_code=synth,
        trade_date=ASOF,
        enable_l2_danger=False,
    )
    assert "danger" not in l2_off[0]["tags"]
    assert l1_off[0]["tags"] == []

    l2_on = [_l2_row("L2D")]
    l1_on = [_l2_row("L1D")]
    assign_exit_tags(
        [],
        l2_on,
        l1_on,
        params=params,
        bar_cache={},
        l2_synth_by_code=synth,
        trade_date=ASOF,
        enable_l2_danger=True,
    )
    assert "danger" in l2_on[0]["tags"]
    assert l1_on[0]["tags"] == []


def test_assign_does_not_mutate_r_solar_rs_vol():
    params = _params()
    stocks = [
        _stock_row(
            "A.SZ",
            right_side=1,
            solar_term="大暑",
            _sigma_pctile=0.99,
            RS=77,
            VOL_score=88,
            T="沸",
        )
    ]
    watch = ("right_side", "solar_term", "T", "RS", "VOL_score", "_sigma_pctile")
    before = {k: deepcopy(stocks[0][k]) for k in watch}
    assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache={"A.SZ": _closes_to_bars([10.0, 11.0])},
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    for k in watch:
        assert stocks[0][k] == before[k]
    assert stocks[0]["tags"] == ["vol_expand"]


def test_tag_rate_warn(capsys):
    params = _params(tag_rate_cap=0.02)
    stocks = [
        _stock_row(
            "A.SZ",
            right_side=1,
            solar_term="大暑",
            _sigma_pctile=0.99,
        )
    ]
    meta = assign_exit_tags(
        stocks,
        [],
        [],
        params=params,
        bar_cache={"A.SZ": _closes_to_bars([10.0, 11.0])},
        l2_synth_by_code={},
        trade_date=ASOF,
    )
    assert meta["stock"] == pytest.approx(1.0)
    err = capsys.readouterr().err
    assert "tag_rate" in err.lower() or "tag rate" in err.lower() or "rate" in err
    assert "stock" in err
    assert ASOF in err
    assert "0.02" in err or "2%" in err


# --- Task 4: daily_run wire ---


def _stub_mini_taxonomy(monkeypatch):
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


def test_exit_tags_wire_replay_and_db(tmp_path, monkeypatch):
    """Params flag on via monkeypatch; daily_run enable_l2_danger=True; L2 no danger on uptrend; L1 []."""
    from scripts.common.bars import bars_conn
    from scripts.common.db import get_conn, init_schema
    from scripts.daily_run import process_day, replay_metrics_cross_section
    from tests.test_daily_run_metrics_wire import (
        SHORT_N,
        _seed_uptrend,
        _short_params,
        _universe_yaml,
        _weekdays_ending,
    )

    params = replace(_short_params(), exit_tags_enabled=True)
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    monkeypatch.setenv("UNIVERSE_YAML", str(_universe_yaml(tmp_path, ["000001.SZ"])))
    monkeypatch.setattr("scripts.daily_run.load_metrics_params", lambda: params)
    monkeypatch.setattr("scripts.common.coverage.DEFAULT_MIN_HISTORY", SHORT_N)
    _stub_mini_taxonomy(monkeypatch)

    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    bconn = bars_conn(bars_path)
    _seed_uptrend(bconn, "000001.SZ", dates, start_px=10.0)
    bconn.close()

    stock_rows, l2_rows, l1_rows, _events = replay_metrics_cross_section(
        D, bars_path=bars_path, params=params, universe=["000001.SZ"]
    )
    assert stock_rows
    assert all(isinstance(r.get("tags"), list) for r in stock_rows)
    assert all("_sigma_pctile" in r for r in stock_rows)
    assert all(isinstance(r.get("tags"), list) for r in l2_rows)
    assert all("danger" not in (r.get("tags") or []) for r in l2_rows)
    assert all(r.get("tags") == [] for r in l1_rows)
    # Basket VOL may be null under short hist (< vol_score_min_samples); do not force-null.

    st = process_day(D, D, bars_path=bars_path, stub_coverage=True)
    assert st == "ok"
    tconn = get_conn()
    init_schema(tconn)
    s_tags = tconn.execute(
        "SELECT tags FROM daily_stock WHERE ts_code=? AND trade_date=?",
        ("000001.SZ", D.isoformat()),
    ).fetchone()[0]
    assert s_tags is not None
    parsed = json.loads(s_tags)
    assert isinstance(parsed, list)
    assert all(t in ("vol_expand", "champagne", "danger") for t in parsed)

    l2_tags = tconn.execute(
        "SELECT tags FROM daily_l2 WHERE code=? AND trade_date=?",
        ("370100", D.isoformat()),
    ).fetchone()[0]
    assert "danger" not in json.loads(l2_tags)

    l1_tags = tconn.execute(
        "SELECT tags FROM daily_l1 WHERE code=? AND trade_date=?",
        ("l1_test", D.isoformat()),
    ).fetchone()[0]
    assert json.loads(l1_tags) == []
    tconn.close()
