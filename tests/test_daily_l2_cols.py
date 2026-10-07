def test_daily_l2_upsert_keeps_member_count_and_amount(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "t.db"))
    from scripts.common import db as dbmod
    conn = dbmod.get_conn()
    dbmod.init_schema(conn)
    dbmod.upsert_daily_l2(
        conn,
        [{
            "trade_date": "2024-01-10",
            "code": "370100",
            "T": None,
            "right_side": None,
            "tag_warm_to_hot": None,
            "tag_warm_to_flat": None,
            "solar_term": None,
            "members_tradable": 0,
            "members_total": 10,
            "warm_to_hot_member_count": 3,
            "amount": 1.5e9,
        }],
    )
    row = conn.execute(
        "SELECT warm_to_hot_member_count, amount, tag_warm_to_hot "
        "FROM daily_l2 WHERE code='370100'"
    ).fetchone()
    assert row[0] == 3
    assert abs(row[1] - 1.5e9) < 1
    assert row[2] is None
