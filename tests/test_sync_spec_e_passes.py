import datetime as dt
from datetime import date, timedelta

from scripts.common.bars import bars_conn, ensure_bars_columns
from scripts.common.calendar import load_trade_dates_from_list
from scripts.sync_bars_sample import main, run_spec_e_passes


def test_run_spec_e_passes_invokes_both(tmp_path, monkeypatch, capsys):
    conn = bars_conn(str(tmp_path / "b.db"))
    seen: list[str] = []
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: seen.append("freeze") or 3,
    )
    monkeypatch.setattr(
        "scripts.common.board_calc.apply_board_calc",
        lambda *a, **k: seen.append("board") or 5,
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.load_hard_freeze_min_suspend_days",
        lambda: 20,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "board_calc_v1"})(),
    )
    run_spec_e_passes(conn, ["600000.SH"], session_asof=dt.date(2024, 1, 9))
    assert seen == ["freeze", "board"]
    out = capsys.readouterr().out
    assert "hard_freeze rows=3" in out
    assert "board_calc rows=5" in out


def test_main_passes_use_full_universe_not_codes_argv(tmp_path, monkeypatch):
    """Spec: passes scan mapped U; --codes only limits OHLC/flags loop."""
    db = tmp_path / "b.db"
    got = {}

    def _passes(conn, codes, *, session_asof):
        got["codes"] = list(codes)
        got["asof"] = session_asof

    monkeypatch.setattr("scripts.sync_bars_sample.run_spec_e_passes", _passes)
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn", lambda: bars_conn(str(db))
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["AAA.SZ", "BBB.SZ"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day",
        lambda: dt.date(2024, 1, 9),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.write_sync_complete",
        lambda *a, **k: None,
    )
    rc = main(
        ["--end", "2024-01-05", "--asof", "2024-01-09", "--codes", "AAA.SZ"]
    )
    assert rc == 0
    assert got["codes"] == ["AAA.SZ", "BBB.SZ"]
    assert got["asof"] == dt.date(2024, 1, 9)  # not --end


def test_incomplete_still_calls_passes_and_keeps_complete_false(
    tmp_path, monkeypatch
):
    db = tmp_path / "b.db"
    calls = {"n": 0, "complete": None}

    def _passes(conn, codes, *, session_asof):
        calls["n"] += 1

    def _wsc(complete, elapsed_min=0.0):
        calls["complete"] = complete

    monkeypatch.setattr("scripts.sync_bars_sample.run_spec_e_passes", _passes)
    monkeypatch.setattr("scripts.sync_bars_sample.write_sync_complete", _wsc)
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn", lambda: bars_conn(str(db))
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["600000.SH", "600001.SH"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.sync_symbol_bars", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day",
        lambda: dt.date(2024, 1, 9),
    )
    rc = main(
        ["--end", "2024-01-09", "--max-codes", "1", "--skip-flags"]
    )
    assert rc == 0
    assert calls["n"] == 1
    assert calls["complete"] is False


def test_main_pass_sets_flag_beyond_ohlc_end_window(tmp_path, monkeypatch):
    """Spec §5.2#8: long suspend outside --end still gets asof flag after pass."""
    days = []
    d = date(2024, 1, 2)
    for _ in range(25):
        days.append(d.isoformat())
        d += timedelta(days=1)
    load_trade_dates_from_list(days)
    end_early = days[4]
    asof = days[-1]
    code = "000001.SZ"
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    ensure_bars_columns(conn)
    for td in days:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, td),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn", lambda: bars_conn(str(db))
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: [code],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day",
        lambda: date.fromisoformat(asof),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.write_sync_complete",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.load_hard_freeze_min_suspend_days",
        lambda: 20,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "board_calc_v1"})(),
    )

    rc = main(
        [
            "--end",
            end_early,
            "--asof",
            asof,
            "--skip-ohlc",
            "--skip-flags",
        ]
    )
    assert rc == 0
    conn = bars_conn(str(db))
    flag = conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
        (code, asof),
    ).fetchone()[0]
    assert flag == 1
    # History before --end must also be rewritten (not fetch-window-only).
    mid = days[19]  # 20th suspend day → streak>=20
    assert (
        conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
            (code, mid),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
            (code, days[18]),
        ).fetchone()[0]
        == 0
    )
