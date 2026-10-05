from scripts.common.db import consumed_signal_sides, get_conn, init_schema, insert_paper_fills


def test_insert_paper_fills_idempotent_same_id(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    row = {
        "fill_id": "abc",
        "track": "L",
        "side": "buy",
        "status": "filled",
        "signal_event_id": 1,
        "ts_code": "000001.SZ",
        "fill_date": "2024-01-08",
    }
    assert insert_paper_fills(conn, [row]) == 1
    assert insert_paper_fills(conn, [row]) == 0
    n = conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0]
    assert n == 1
    conn.close()


def test_consumed_signal_sides_track_l_only(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    insert_paper_fills(
        conn,
        [
            {
                "fill_id": "h1",
                "track": "H",
                "side": "buy",
                "status": "filled",
                "signal_event_id": 9,
                "fill_date": "2024-01-08",
            },
            {
                "fill_id": "l1",
                "track": "L",
                "side": "buy",
                "status": "data_gap",
                "signal_event_id": 10,
                "fill_date": "2024-01-08",
            },
        ],
    )
    assert consumed_signal_sides(conn) == {(10, "buy")}
    conn.close()


def test_insert_skips_same_event_side_fill_date(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    row = {
        "fill_id": "a",
        "track": "L",
        "side": "sell",
        "status": "unfilled_sell",
        "signal_event_id": 3,
        "fill_date": "2024-01-08",
    }
    retry_same_day = dict(row, fill_id="b")
    later = dict(row, fill_id="c", fill_date="2024-01-09", status="filled")
    assert insert_paper_fills(conn, [row]) == 1
    assert insert_paper_fills(conn, [retry_same_day]) == 0
    assert insert_paper_fills(conn, [later]) == 1
    conn.close()


def test_insert_l_not_blocked_by_h_same_event_day(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    h = {
        "fill_id": "h1",
        "track": "H",
        "side": "buy",
        "status": "filled",
        "signal_event_id": 7,
        "fill_date": "2024-01-08",
    }
    l = dict(h, fill_id="l1", track="L")
    assert insert_paper_fills(conn, [h]) == 1
    assert insert_paper_fills(conn, [l]) == 1
    n = conn.execute("SELECT COUNT(*) FROM paper_fill").fetchone()[0]
    assert n == 2
    conn.close()


def test_shadow_book_roundtrip_in_trend_db(tmp_path, monkeypatch):
    from scripts.eval.book import BookState, Position
    from scripts.eval.costs import load_costs
    from scripts.eval.shadow_store import load_shadow_book, save_shadow_book

    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    costs = load_costs()
    book = BookState(cash=1.0, last_equity=2.0)
    book.positions["000001.SZ"] = Position(
        shares=100, entry_date="2024-01-08", entry_px=10.0, signal_date="2024-01-05"
    )
    save_shadow_book(conn, book)
    loaded = load_shadow_book(conn, costs)
    assert loaded.positions["000001.SZ"].shares == 100
    assert loaded.cash == 1.0
    conn.close()
