"""Purge non-§4 / 801xxx daily_l2 rows for a trade_date."""
import sqlite3

from scripts.common.db import init_schema, purge_invalid_daily_l2, upsert_daily_l2


def test_purge_removes_801_and_keeps_section4():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    td = "2026-09-30"
    upsert_daily_l2(
        conn,
        [
            {
                "trade_date": td,
                "code": "370100",
                "T": "凉",
                "members_total": 1,
                "members_tradable": 1,
            },
            {
                "trade_date": td,
                "code": "801180",
                "T": "沸",
                "right_side": 1,
                "members_total": 1,
                "members_tradable": 1,
            },
            {
                "trade_date": td,
                "code": "801780",
                "T": "平",
                "members_total": 3,
                "members_tradable": 3,
            },
        ],
        commit=True,
    )
    n = purge_invalid_daily_l2(conn, td, allowed={"370100", "460700"})
    assert n == 2
    codes = {
        r[0]
        for r in conn.execute(
            "SELECT code FROM daily_l2 WHERE trade_date=?", (td,)
        )
    }
    assert codes == {"370100"}
