"""Sync skip rules, budget, and GITHUB_OUTPUT complete flag."""
from datetime import date

from scripts.common.bars import apply_flag_rows, bars_conn
from scripts.sync_bars_sample import (
    ohlc_end_row_exists,
    skip_flags,
    skip_ohlc,
    write_sync_complete,
)


def test_skip_ohlc_only_when_end_row_exists(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    end = date(2026, 9, 30)
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, close_qfq, bar_source)
        VALUES ('000001.SZ', '2026-09-29', 10, 'sina')
        """
    )
    conn.commit()
    assert ohlc_end_row_exists(conn, "000001.SZ", end) is False
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, close_qfq, bar_source)
        VALUES ('000001.SZ', '2026-09-30', 11, 'sina')
        """
    )
    conn.commit()
    assert ohlc_end_row_exists(conn, "000001.SZ", end) is True
    assert skip_ohlc(conn, "000001.SZ", end) is False
    conn.close()


def test_skip_ohlc_when_end_row_and_252_sessions(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    end = date(2026, 9, 30)
    for i in range(252):
        d = date(2025, 9, 30).toordinal() + i
        from datetime import date as date_cls

        td = date_cls.fromordinal(d).isoformat()
        conn.execute(
            """
            INSERT INTO bars (ts_code, trade_date, close_qfq, bar_source)
            VALUES ('000001.SZ', ?, 10, 'sina')
            """,
            (td,),
        )
    conn.commit()
    last = conn.execute(
        "SELECT MAX(trade_date) FROM bars WHERE ts_code='000001.SZ'"
    ).fetchone()[0]
    end = date.fromisoformat(last)
    assert skip_ohlc(conn, "000001.SZ", end) is True
    conn.close()


def test_skip_flags_requires_flag_source(tmp_path):
    conn = bars_conn(str(tmp_path / "bars.db"))
    end = date(2026, 9, 30)
    conn.execute(
        """
        INSERT INTO bars (ts_code, trade_date, close_qfq, bar_source)
        VALUES ('000001.SZ', '2026-09-30', 11, 'sina')
        """
    )
    conn.commit()
    assert skip_flags(conn, "000001.SZ", end) is False
    apply_flag_rows(conn, [("000001.SZ", "2026-09-30", 0, 0)])
    assert skip_flags(conn, "000001.SZ", end) is True
    conn.close()


def test_github_output_sync_complete(tmp_path, monkeypatch):
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    write_sync_complete(True)
    write_sync_complete(False)
    write_sync_complete(True, elapsed_min=201.0)
    text = out.read_text(encoding="utf-8")
    assert "sync_complete=true" in text
    assert "sync_complete=false" in text
    assert "run_deferred=false" in text
    assert "run_deferred=true" in text


def test_max_codes_counts_work_not_list_prefix(tmp_path, monkeypatch):
    """First ticker already skippable; max-codes=1 must work the next name."""
    from scripts.sync_bars_sample import main

    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    end = date(2026, 9, 30)
    for i in range(252):
        td = date.fromordinal(date(2025, 9, 30).toordinal() + i).isoformat()
        conn.execute(
            """
            INSERT INTO bars (ts_code, trade_date, close_qfq, bar_source)
            VALUES ('000001.SZ', ?, 10, 'sina')
            """,
            (td,),
        )
    # Ensure end day exists for skip_ohlc
    conn.execute(
        """
        INSERT OR REPLACE INTO bars (ts_code, trade_date, close_qfq, bar_source)
        VALUES ('000001.SZ', ?, 11, 'sina')
        """,
        (end.isoformat(),),
    )
    conn.commit()
    conn.close()

    calls = []

    def _ohlc(conn, code, end, limiter=None):
        calls.append(code)
        return 1

    monkeypatch.setattr("scripts.sync_bars_sample.sync_symbol_bars", _ohlc)
    monkeypatch.setattr("scripts.sync_bars_sample.sync_baostock_flags", lambda *a, **k: 0)
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn",
        lambda: bars_conn(bars_path),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day",
        lambda: end,
    )
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    rc = main(
        [
            "--codes",
            "000001.SZ,000002.SZ,600000.SH",
            "--end",
            end.isoformat(),
            "--max-codes",
            "1",
            "--skip-flags",
        ]
    )
    assert rc == 0
    assert calls == ["000002.SZ"]
    assert "000001.SZ" not in calls
    assert "sync_complete=false" in out.read_text(encoding="utf-8")


def test_with_limits_skipped_when_end_not_asof(tmp_path, monkeypatch):
    from scripts.sync_bars_sample import main

    called = []

    def _limits(*_a, **_k):
        called.append(True)
        return 0

    monkeypatch.setattr("scripts.sync_bars_sample.sync_em_limits_asof", _limits)
    monkeypatch.setattr("scripts.sync_bars_sample.sync_symbol_bars", lambda *a, **k: 0)
    monkeypatch.setattr("scripts.sync_bars_sample.sync_baostock_flags", lambda *a, **k: 0)
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn",
        lambda: bars_conn(str(tmp_path / "bars.db")),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day",
        lambda: date(2026, 10, 9),
    )
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    rc = main(
        [
            "--codes",
            "000001.SZ",
            "--end",
            "2026-09-30",
            "--with-limits",
            "--skip-ohlc",
            "--skip-flags",
        ]
    )
    assert rc == 0
    assert called == []
