from datetime import date, timedelta

from scripts.common.calendar import load_trade_dates_from_list, trading_days_inclusive
from scripts.common.db import get_conn, init_schema
from scripts.eval.book import BookState
from scripts.eval.costs import load_costs
from scripts.eval.paper_book import pair_rounds, replay_window, window_kpis


def _bar(open_raw=10.0, close_raw=10.0, up=20.0, down=1.0):
    return {
        "open_raw": open_raw,
        "close_raw": close_raw,
        "limit_up": up,
        "limit_down": down,
        "is_suspended": 0,
    }


def test_audit_walks_trade_days_not_civil():
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    fri = date(2024, 1, 5)
    sat = fri + timedelta(days=1)
    mon = date(2024, 1, 8)
    days = trading_days_inclusive(fri, mon)
    assert sat not in days
    assert days == [fri, mon]
    costs = load_costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    result = replay_window(
        fri,
        mon,
        signals=[
            {
                "id": 1,
                "event": "ENTER_RIGHT",
                "ts_code": "000001.SZ",
                "trade_date": "2024-01-05",
                "RS": 1.0,
            }
        ],
        bars_by_day={
            "2024-01-05": {"000001.SZ": _bar()},
            "2024-01-08": {"000001.SZ": _bar()},
        },
        costs=costs,
        book=book,
    )
    bought = [f for f in result["fills"] if f["status"] == "filled" and f["side"] == "buy"]
    assert len(bought) == 1
    assert bought[0]["fill_date"] == "2024-01-08"
    assert bought[0]["track"] == "H"
    assert result["kpi"]["n_open_end"] == 1
    assert result["kpi"]["win_rate"] is None


def test_window_kpis_pairs_rounds_not_first_ticker_buy():
    """Second round of the same name must not inherit the first entry px."""
    fills = [
        {"side": "buy", "status": "filled", "ts_code": "000001.SZ", "px": 10.0, "signal_event_id": 1},
        {"side": "sell", "status": "filled", "ts_code": "000001.SZ", "px": 10.5, "signal_event_id": 2},
        {"side": "buy", "status": "filled", "ts_code": "000001.SZ", "px": 12.0, "signal_event_id": 3},
        {"side": "sell", "status": "filled", "ts_code": "000001.SZ", "px": 11.0, "signal_event_id": 4},
    ]
    rounds = pair_rounds(fills)
    assert len(rounds) == 2
    assert rounds[0]["buy"]["px"] == 10.0
    assert rounds[1]["buy"]["px"] == 12.0
    book = BookState(cash=0, last_equity=0)
    kpi = window_kpis(fills, book)
    assert kpi["n_closed"] == 2
    assert kpi["n_open_end"] == 0
    assert kpi["win_rate"] == 0.5


def test_replay_does_not_write_paper_fill(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    conn.close()
    costs = load_costs()
    replay_window(
        date(2024, 1, 5),
        date(2024, 1, 8),
        signals=[
            {
                "id": 1,
                "event": "ENTER_RIGHT",
                "ts_code": "000001.SZ",
                "trade_date": "2024-01-05",
                "RS": 1.0,
            }
        ],
        bars_by_day={"2024-01-08": {"000001.SZ": _bar()}},
        costs=costs,
        book=BookState(cash=costs.initial_cash, last_equity=costs.initial_cash),
    )
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0]
    conn.close()
    assert n == 0


def test_paper_book_main_does_not_write_paper_fill(tmp_path, monkeypatch):
    import json

    from scripts.eval.paper_book import main

    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    conn.close()
    sig = tmp_path / "signals.json"
    sig.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "event": "ENTER_RIGHT",
                    "ts_code": "000001.SZ",
                    "trade_date": "2024-01-05",
                    "RS": 1.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    rc = main(
        [
            "--from",
            "2024-01-05",
            "--to",
            "2024-01-08",
            "--signals-json",
            str(sig),
            "--bars-db",
            str(tmp_path / "missing-bars.db"),
        ]
    )
    assert rc == 0
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0]
    conn.close()
    assert n == 0
