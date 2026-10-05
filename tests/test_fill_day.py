from datetime import date

from scripts.common.calendar import load_trade_dates_from_list, next_trade_date
from scripts.eval.book import BookState
from scripts.eval.costs import load_costs
from scripts.eval.fill_day import fill_day, round_kpis


def _costs():
    return load_costs()


def _bar(open_raw=10.0, close_raw=10.0, up=11.0, down=9.0, suspended=0):
    return {
        "open_raw": open_raw,
        "close_raw": close_raw,
        "limit_up": up,
        "limit_down": down,
        "is_suspended": suspended,
    }


def test_load_costs_v1():
    c = load_costs()
    assert c.cost_version == "v1"
    assert c.N_cap == 20
    assert c.fill_price == "open_raw"


def test_empty_book_mtm_is_cash():
    b = BookState(cash=1_000_000, last_equity=1_000_000)
    assert b.mtm({}) == 1_000_000


def test_fill_fri_enter_mon_buy():
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    fri = date(2024, 1, 5)
    mon = date(2024, 1, 8)
    assert next_trade_date(fri) == mon
    costs = _costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    fills = fill_day(
        mon.isoformat(),
        [{"event": "ENTER_RIGHT", "ts_code": "000001.SZ", "trade_date": fri.isoformat(), "id": 1, "RS": 1.0}],
        book,
        {"000001.SZ": _bar()},
        costs,
        track="H",
        run_id="fri_mon",
    )
    bought = [f for f in fills if f["status"] == "filled" and f["side"] == "buy"]
    assert len(bought) == 1
    assert bought[0]["fill_date"] == mon.isoformat()
    assert bought[0]["signal_date"] == fri.isoformat()
    assert bought[0]["intent_date"] == mon.isoformat()
    assert bought[0]["rule_id"] == "mvp_right_side_v1"
    assert "000001.SZ" in book.positions


def test_fill_enter_right_only():
    costs = _costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    fills = fill_day(
        "2024-01-08",
        [{"event": "WARM_TO_HOT", "ts_code": "000001.SZ", "trade_date": "2024-01-05", "id": 2}],
        book,
        {"000001.SZ": _bar()},
        costs,
    )
    assert book.positions == {}
    assert not any(f["side"] == "buy" and f["status"] == "filled" for f in fills)


def test_fill_forced_exit_st():
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    assert next_trade_date(date(2024, 1, 8)) == date(2024, 1, 9)
    costs = _costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    fill_day(
        "2024-01-08",
        [{"event": "ENTER_RIGHT", "ts_code": "000001.SZ", "trade_date": "2024-01-05", "id": 1, "RS": 1}],
        book,
        {"000001.SZ": _bar()},
        costs,
    )
    assert "000001.SZ" in book.positions
    fills = fill_day(
        "2024-01-09",
        [
            {
                "event": "EXIT_RIGHT",
                "ts_code": "000001.SZ",
                "trade_date": "2024-01-08",
                "id": 3,
                "detail": {"exit_kind": "forced_exit_untradable"},
            }
        ],
        book,
        {"000001.SZ": _bar(open_raw=10.2, close_raw=10.1)},
        costs,
    )
    sold = [f for f in fills if f["side"] == "sell" and f["status"] == "filled"]
    assert len(sold) == 1
    assert sold[0]["exit_kind"] == "forced_exit_untradable"
    assert sold[0]["intent_date"] == "2024-01-09"
    assert "000001.SZ" not in book.positions


def test_exit_kind_from_detail_json_string():
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    costs = _costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    fill_day(
        "2024-01-08",
        [{"event": "ENTER_RIGHT", "ts_code": "000001.SZ", "trade_date": "2024-01-05", "id": 1, "RS": 1}],
        book,
        {"000001.SZ": _bar()},
        costs,
    )
    fills = fill_day(
        "2024-01-09",
        [
            {
                "event": "EXIT_RIGHT",
                "ts_code": "000001.SZ",
                "trade_date": "2024-01-08",
                "id": 4,
                "detail": '{"exit_kind": "temperature"}',
            }
        ],
        book,
        {"000001.SZ": _bar(open_raw=10.2)},
        costs,
    )
    sold = [f for f in fills if f["side"] == "sell" and f["status"] == "filled"]
    assert sold[0]["exit_kind"] == "temperature"


def test_pending_sell_intent_date_stays_first_session():
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"])
    costs = _costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    fill_day(
        "2024-01-08",
        [{"event": "ENTER_RIGHT", "ts_code": "000001.SZ", "trade_date": "2024-01-05", "id": 1, "RS": 1}],
        book,
        {"000001.SZ": _bar()},
        costs,
    )
    fill_day(
        "2024-01-09",
        [
            {
                "event": "EXIT_RIGHT",
                "ts_code": "000001.SZ",
                "trade_date": "2024-01-08",
                "id": 5,
                "detail": {"exit_kind": "temperature"},
            }
        ],
        book,
        {"000001.SZ": _bar(open_raw=9.0, down=9.0)},
        costs,
    )
    assert book.pending_sells
    fills = fill_day(
        "2024-01-10",
        [],
        book,
        {"000001.SZ": _bar(open_raw=10.0)},
        costs,
    )
    sold = [f for f in fills if f["side"] == "sell" and f["status"] == "filled"]
    assert sold[0]["fill_date"] == "2024-01-10"
    assert sold[0]["intent_date"] == "2024-01-09"


def test_fill_open_end_kpi():
    costs = _costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    fills = fill_day(
        "2024-01-08",
        [{"event": "ENTER_RIGHT", "ts_code": "000001.SZ", "trade_date": "2024-01-05", "id": 1, "RS": 1}],
        book,
        {"000001.SZ": _bar()},
        costs,
    )
    kpi = round_kpis(fills, book)
    assert kpi["n_open_end"] >= 1
    assert kpi["n_closed"] == 0
    assert kpi["win_rate"] is None


def test_fill_open_end_does_not_enter_win_rate_with_closed():
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    costs = _costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    a = fill_day(
        "2024-01-08",
        [
            {"event": "ENTER_RIGHT", "ts_code": "000001.SZ", "trade_date": "2024-01-05", "id": 1, "RS": 2},
            {"event": "ENTER_RIGHT", "ts_code": "000002.SZ", "trade_date": "2024-01-05", "id": 2, "RS": 1},
        ],
        book,
        {"000001.SZ": _bar(), "000002.SZ": _bar()},
        costs,
    )
    b = fill_day(
        "2024-01-09",
        [
            {
                "event": "EXIT_RIGHT",
                "ts_code": "000001.SZ",
                "trade_date": "2024-01-08",
                "id": 3,
                "detail": {"exit_kind": "temperature"},
            }
        ],
        book,
        {"000001.SZ": _bar(open_raw=11.0, close_raw=11.0), "000002.SZ": _bar()},
        costs,
    )
    kpi = round_kpis(a + b, book)
    assert kpi["n_closed"] == 1
    assert kpi["n_open_end"] == 1
    assert kpi["win_rate"] == 1.0


def test_buy_data_gap_without_limits():
    costs = _costs()
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    bar = _bar()
    bar["limit_up"] = None
    bar["limit_down"] = None
    fills = fill_day(
        "2024-01-08",
        [{"event": "ENTER_RIGHT", "ts_code": "000001.SZ", "trade_date": "2024-01-05", "id": 1}],
        book,
        {"000001.SZ": bar},
        costs,
    )
    assert fills[0]["status"] == "data_gap"
    assert book.positions == {}
