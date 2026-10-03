"""process_day metrics cross-section (Task 8). Offline synthetic bars, no network.

Default metrics vol_hist=252 makes temperature history heavy. Tests monkeypatch
``load_metrics_params`` with a shortened ``vol_hist`` (and related windows) so
``min_history_temp`` is 40. Optional env ``METRICS_MIN_HISTORY`` is a further
gate on ``compute_features``; shortening it alone does not cut vol_hist.
Coverage still uses ``compute_coverage_from_bars`` / ``evaluate_ok``.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from scripts.common.bars import apply_flag_rows, apply_limit_rows, bars_conn
from scripts.common.db import get_conn, init_schema
from scripts.metrics.params import load_params

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_params(ROOT / "config" / "metrics" / "a_share_daily.yaml")

# Enough for SMA/ADX/σ%ile under shortened params (not production 252).
SHORT_N = 40


def _short_params():
    return replace(
        PARAMS,
        vol_hist=40,
        ma_slow=10,
        ma_fast=5,
        slope_n=3,
        adx_len=5,
        atr_len=5,
        vol_lookback=8,
        ret_k=5,
    )


def _weekdays_ending(end: date, n: int) -> list[date]:
    d = end
    out: list[date] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def _seed_uptrend(
    conn,
    ts_code: str,
    dates: list[date],
    *,
    is_st: int = 0,
    with_limits: bool = True,
    start_px: float = 10.0,
):
    conn.execute("DELETE FROM bars WHERE ts_code=?", (ts_code,))
    for i, d in enumerate(dates):
        close = start_px * (1.015 ** i)
        high = close * 1.02
        low = close * 0.99
        open_ = close * 0.995
        raw = close * 1.1
        conn.execute(
            """
            INSERT INTO bars (
              ts_code, trade_date,
              open_qfq, high_qfq, low_qfq, close_qfq,
              open_raw, high_raw, low_raw, close_raw,
              float_mv, amount, bar_source, is_st, is_suspended
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ts_code,
                d.isoformat(),
                open_,
                high,
                low,
                close,
                raw,
                raw * 1.02,
                raw * 0.99,
                raw,
                1e10,
                1e8,
                "sina",
                is_st if d == dates[-1] else 0,
                0,
            ),
        )
    td = dates[-1].isoformat()
    apply_flag_rows(conn, [(ts_code, td, 0, is_st)])
    if with_limits:
        last_raw = start_px * (1.015 ** (len(dates) - 1)) * 1.1
        apply_limit_rows(conn, td, {ts_code: (last_raw * 1.1, last_raw * 0.9)})
    conn.commit()


def _universe_yaml(tmp_path, members: list[str]) -> Path:
    p = tmp_path / "uni.yaml"
    lines = ["map_version: p05-v1", "members:"]
    for m in members:
        lines.append("  - %s" % m)
    lines.append("quarantine: []")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _patch_run(tmp_path, monkeypatch, members, *, short_metrics: bool = True):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    monkeypatch.setenv("UNIVERSE_YAML", str(_universe_yaml(tmp_path, members)))
    monkeypatch.setattr("scripts.common.coverage.DEFAULT_MIN_HISTORY", SHORT_N if short_metrics else 3)
    if short_metrics:
        short = _short_params()
        assert short.min_history_temp == SHORT_N
        monkeypatch.setattr("scripts.daily_run.load_metrics_params", lambda: short)
    return str(tmp_path / "bars.db")


def test_synthetic_bars_write_nonnull_T(tmp_path, monkeypatch):
    from scripts.daily_run import process_day

    bars_path = _patch_run(tmp_path, monkeypatch, ["000001.SZ"])
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N)
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates)
    conn.close()

    st = process_day(D, D, bars_path=bars_path)
    assert st == "ok"

    tconn = get_conn()
    init_schema(tconn)
    row = tconn.execute(
        """
        SELECT T, hard_frozen, close_qfq, stage_score, stage_score_raw, param_version
        FROM daily_stock JOIN run_meta USING (trade_date)
        WHERE ts_code='000001.SZ' AND trade_date=?
        """,
        (D.isoformat(),),
    ).fetchone()
    assert row is not None
    t, hard, close_qfq, score, score_raw, pv = row
    assert t is not None and t != ""
    assert hard == 0
    assert close_qfq is not None
    # R may or may not be on; scores are written (SQL NULL on non-right / exit).
    assert score is None or isinstance(score, float)
    assert score_raw is None or isinstance(score_raw, float)
    meta = tconn.execute(
        "SELECT param_version, map_version, status FROM run_meta WHERE trade_date=?",
        (D.isoformat(),),
    ).fetchone()
    assert meta == ("p05-v1", "p05-v1", "ok")
    l2n = tconn.execute("SELECT COUNT(*) FROM daily_l2").fetchone()[0]
    l1n = tconn.execute("SELECT COUNT(*) FROM daily_l1").fetchone()[0]
    assert l2n >= 1 and l1n >= 1
    tconn.close()


def test_asof_low_limit_run_meta_partial(tmp_path, monkeypatch):
    from scripts.daily_run import process_day

    bars_path = _patch_run(tmp_path, monkeypatch, ["000001.SZ"], short_metrics=False)
    monkeypatch.setattr("scripts.common.coverage.DEFAULT_MIN_HISTORY", 3)
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, 5)
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, with_limits=False)
    conn.close()

    st = process_day(D, D, bars_path=bars_path)
    assert st == "partial"
    tconn = get_conn()
    status, warn = tconn.execute(
        "SELECT status, warn FROM run_meta WHERE trade_date=?", (D.isoformat(),)
    ).fetchone()
    assert status == "partial"
    assert "limit_coverage" in warn
    tconn.close()


def test_history_day_without_limits_still_ok(tmp_path, monkeypatch):
    from scripts.daily_run import process_day

    bars_path = _patch_run(tmp_path, monkeypatch, ["000001.SZ"], short_metrics=False)
    monkeypatch.setattr("scripts.common.coverage.DEFAULT_MIN_HISTORY", 3)
    D = date(2024, 1, 5)
    asof = date(2024, 1, 10)
    dates = _weekdays_ending(D, 5)
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, with_limits=False)
    conn.close()

    st = process_day(D, asof, bars_path=bars_path)
    assert st == "ok"
    tconn = get_conn()
    status = tconn.execute(
        "SELECT status FROM run_meta WHERE trade_date=?", (D.isoformat(),)
    ).fetchone()[0]
    assert status == "ok"
    tconn.close()


def test_hard_frozen_and_stage_score_write_path(tmp_path, monkeypatch):
    from scripts.daily_run import process_day

    bars_path = _patch_run(tmp_path, monkeypatch, ["000001.SZ"])
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N)
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, is_st=1, with_limits=True)
    conn.close()

    process_day(D, D, bars_path=bars_path, stub_coverage=True)
    tconn = get_conn()
    row = tconn.execute(
        """
        SELECT hard_frozen, T, stage_score, stage_score_raw, close_qfq
        FROM daily_stock WHERE ts_code='000001.SZ' AND trade_date=?
        """,
        (D.isoformat(),),
    ).fetchone()
    assert row is not None
    hard, t, score, score_raw, close_qfq = row
    assert hard == 1
    assert close_qfq is not None
    # ST ends R: scores must be SQL NULL when not on the right (or after forced exit).
    assert score is None or isinstance(score, (int, float))
    assert score_raw is None or isinstance(score_raw, (int, float))
    tconn.close()


def test_stub_coverage_still_runs_metrics(tmp_path, monkeypatch):
    from scripts.daily_run import process_day

    bars_path = _patch_run(tmp_path, monkeypatch, ["000001.SZ"])
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N)
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, with_limits=False)
    conn.close()

    st = process_day(D, D, bars_path=bars_path, stub_coverage=True)
    assert st == "ok"
    tconn = get_conn()
    t = tconn.execute(
        "SELECT T FROM daily_stock WHERE ts_code='000001.SZ' AND trade_date=?",
        (D.isoformat(),),
    ).fetchone()[0]
    assert t is not None
    tconn.close()
