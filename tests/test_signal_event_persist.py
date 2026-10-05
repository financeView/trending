"""UPSERT daily_* + signal_event append/supersede + schema migrate."""
from __future__ import annotations

import sqlite3

from scripts.common import db as dbmod
from scripts.metrics.aggregate import (
    MEMBER_SET,
    aggregate_l1,
    aggregate_l2,
    member_closure,
    normalize_weights,
    weight_raw,
)


def test_migrate_old_daily_stock_adds_score_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE daily_stock (
          trade_date TEXT NOT NULL,
          ts_code TEXT NOT NULL,
          T TEXT,
          PRIMARY KEY (trade_date, ts_code)
        )
        """
    )
    conn.commit()
    cols_before = {r[1] for r in conn.execute("PRAGMA table_info(daily_stock)")}
    assert "stage_score" not in cols_before
    assert "stage_score_raw" not in cols_before
    assert "hard_frozen" not in cols_before

    dbmod.migrate_schema(conn)
    dbmod.migrate_schema(conn)  # idempotent

    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_stock)")}
    for name in (
        "stage_score",
        "stage_score_raw",
        "hard_frozen",
        "close_qfq",
        "float_mv",
        "solar_term",
        "tag_warm_to_hot",
        "tag_warm_to_flat",
    ):
        assert name in cols

    conn.execute(
        """
        INSERT INTO daily_stock (trade_date, ts_code, T, stage_score, stage_score_raw)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("2024-01-05", "000001.SZ", "平", None, None),
    )
    conn.commit()
    row = conn.execute(
        "SELECT stage_score, stage_score_raw FROM daily_stock WHERE ts_code='000001.SZ'"
    ).fetchone()
    assert row == (None, None)

    l2_cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_l2)")}
    assert "hard_frozen" not in l2_cols
    assert "stage_score" not in l2_cols
    assert "members_tradable" in l2_cols
    conn.close()


def test_upsert_daily_stock_null_scores_and_idempotent():
    conn = sqlite3.connect(":memory:")
    dbmod.init_schema(conn)
    row = {
        "trade_date": "2024-01-05",
        "ts_code": "000001.SZ",
        "T": "平",
        "S_temp": 0.0,
        "RS": None,
        "right_side": False,
        "tag_warm_to_hot": False,
        "tag_warm_to_flat": True,
        "solar_term": "立秋",
        "hard_frozen": False,
        "close_qfq": 10.5,
        "float_mv": None,
        "stage_score": None,
        "stage_score_raw": None,
    }
    assert dbmod.upsert_daily_stock(conn, [row]) == 1
    assert dbmod.upsert_daily_stock(conn, [row]) == 1
    n = conn.execute("SELECT COUNT(*) FROM daily_stock").fetchone()[0]
    assert n == 1
    got = conn.execute(
        """
        SELECT T, stage_score, stage_score_raw, hard_frozen, close_qfq, float_mv,
               tag_warm_to_flat, solar_term
        FROM daily_stock
        """
    ).fetchone()
    assert got[0] == "平"
    assert got[1] is None
    assert got[2] is None
    assert got[3] == 0
    assert got[4] == 10.5
    assert got[5] is None
    assert got[6] == 1
    assert got[7] == "立秋"
    conn.close()


def test_upsert_daily_l2_l1_core_cols_no_stock_scores():
    conn = sqlite3.connect(":memory:")
    dbmod.init_schema(conn)
    basket = {
        "trade_date": "2024-01-05",
        "code": "801780",
        "T": "温",
        "S_temp": 0.2,
        "RS": 55.0,
        "right_side": 1,
        "tag_warm_to_hot": 1,
        "tag_warm_to_flat": 0,
        "solar_term": "谷雨",
        "members_tradable": 2,
        "members_total": 3,
    }
    dbmod.upsert_daily_l2(conn, [basket])
    dbmod.upsert_daily_l1(
        conn,
        [{**basket, "code": "l1_finance"}],
    )
    l2_info = {r[1] for r in conn.execute("PRAGMA table_info(daily_l2)")}
    l1_info = {r[1] for r in conn.execute("PRAGMA table_info(daily_l1)")}
    assert "hard_frozen" not in l2_info
    assert "stage_score" not in l2_info
    assert "stage_score_raw" not in l1_info
    row = conn.execute(
        "SELECT code, T, members_tradable, solar_term FROM daily_l2"
    ).fetchone()
    assert row == ("801780", "温", 2, "谷雨")
    conn.close()


def test_signal_event_supersede_on_payload_change_only():
    conn = sqlite3.connect(":memory:")
    dbmod.init_schema(conn)
    base = {
        "trade_date": "2024-01-05",
        "ts_code": "000001.SZ",
        "event": "EXIT_RIGHT",
        "T": "平",
        "RS": None,
        "detail": {"exit_kind": "temperature"},
    }
    ids1 = dbmod.append_signal_events(conn, [base])
    assert len(ids1) == 1
    ids_same = dbmod.append_signal_events(
        conn,
        [
            {
                **base,
                "detail": '{"exit_kind": "temperature"}',
            }
        ],
    )
    assert ids_same == []
    n = conn.execute("SELECT COUNT(*) FROM signal_event").fetchone()[0]
    assert n == 1
    active = conn.execute(
        "SELECT COUNT(*) FROM signal_event WHERE superseded_by IS NULL"
    ).fetchone()[0]
    assert active == 1

    ids2 = dbmod.append_signal_events(
        conn,
        [
            {
                **base,
                "detail": {"exit_kind": "forced_exit_untradable"},
            }
        ],
    )
    assert len(ids2) == 1
    n = conn.execute("SELECT COUNT(*) FROM signal_event").fetchone()[0]
    assert n == 2
    old = conn.execute(
        "SELECT superseded_by FROM signal_event WHERE id=?", (ids1[0],)
    ).fetchone()[0]
    assert old == ids2[0]
    live = conn.execute(
        """
        SELECT id, detail FROM signal_event
        WHERE trade_date='2024-01-05' AND ts_code='000001.SZ'
          AND event='EXIT_RIGHT' AND superseded_by IS NULL
        """
    ).fetchall()
    assert len(live) == 1
    assert live[0][0] == ids2[0]
    assert "forced_exit_untradable" in live[0][1]
    conn.close()


def test_aggregate_mvp_null_mv_and_l1_closure_once():
    assert MEMBER_SET == "tradable"
    assert weight_raw(None) == 1.0
    w = normalize_weights([None, 3.0])
    assert abs(w[0] - 0.25) < 1e-12
    assert abs(w[1] - 0.75) < 1e-12

    l2_members = {
        "801780": ["000001.SZ", "600000.SH", "601318.SH"],
        "801180": ["000002.SZ"],
        "801120": ["600519.SH"],
    }
    l1_to_l2 = {
        "l1_finance": ["801780"],
        "l1_property_infra": ["801180"],
        "l1_staples": ["801120"],
    }
    closed = member_closure(["801780", "801180"], l2_members)
    assert closed == ["000001.SZ", "600000.SH", "601318.SH", "000002.SZ"]

    stocks = [
        {
            "trade_date": "2024-01-05",
            "ts_code": "000001.SZ",
            "T": "热",
            "S_temp": 1.0,
            "float_mv": None,
            "right_side": 1,
            "solar_term": "谷雨",
        },
        {
            "trade_date": "2024-01-05",
            "ts_code": "600000.SH",
            "T": "温",
            "S_temp": 0.0,
            "float_mv": 3.0,
            "right_side": 0,
            "solar_term": "立夏",
        },
    ]
    l2 = {r["code"]: r for r in aggregate_l2(stocks, "2024-01-05", l2_members=l2_members)}
    assert l2["801780"]["members_tradable"] == 2
    assert l2["801780"]["members_total"] == 3
    assert "stage_score" not in l2["801780"]
    l1 = {
        r["code"]: r
        for r in aggregate_l1(
            stocks, "2024-01-05", l1_to_l2=l1_to_l2, l2_members=l2_members
        )
    }
    assert set(l1) == {"l1_finance", "l1_property_infra", "l1_staples"}
    assert l1["l1_finance"]["members_total"] == 3
    assert l1["l1_finance"]["members_tradable"] == 2
    # L1 uses stock members, not nested L2 T
    assert l1["l1_finance"]["T"] == l2["801780"]["T"]
