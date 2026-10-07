from scripts.daily_run import _basket_asof_row


def test_count_uses_member_set_not_sw_l2_field():
    members = ["000001.SZ"]
    rows = [
        {
            "ts_code": "000001.SZ",
            "sw_l2_code": "WRONG",
            "l1_id": None,
            "tag_warm_to_hot": 1,
            "amount": 1e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
        {
            "ts_code": "000002.SZ",
            "sw_l2_code": "370100",
            "l1_id": "l1_health",
            "tag_warm_to_hot": 1,
            "amount": 2e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
    ]
    out = _basket_asof_row(
        "370100",
        members,
        rows,
        snap=None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert out["warm_to_hot_member_count"] == 1
    assert out["amount"] == 1e8
    assert out["T"] is None
    assert out["tag_warm_to_hot"] is None


def test_l1_count_ignores_l1_id_outside_closure():
    members = ["000001.SZ"]
    rows = [
        {
            "ts_code": "000001.SZ",
            "l1_id": "other",
            "tag_warm_to_hot": 1,
            "amount": 1e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
        {
            "ts_code": "999999.SZ",
            "l1_id": "l1_health",
            "tag_warm_to_hot": 1,
            "amount": 9e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
    ]
    out = _basket_asof_row(
        "l1_health",
        members,
        rows,
        snap=None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert out["warm_to_hot_member_count"] == 1
    assert out["amount"] == 1e8


def test_l1_density_only_accepts_stock_rows_not_l2_payload():
    """Spec §7.3: L2 industry tag must not feed L1 density.

    `_basket_asof_row` has no daily_l2 parameter — lock by API + cool stocks → 0.
    Also reject accidental 'code' keys that look like L2 baskets in stock_rows.
    """
    import inspect
    from scripts.daily_run import _basket_asof_row as fn

    assert "daily_l2" not in inspect.signature(fn).parameters
    members = ["000001.SZ"]
    rows = [
        {
            "ts_code": "000001.SZ",
            "tag_warm_to_hot": 0,
            "amount": 1e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
        # decoy: looks like an L2 basket row mistakenly mixed into stock_rows
        {
            "code": "370100",
            "tag_warm_to_hot": 1,
            "amount": 9e9,
        },
    ]
    out = fn(
        "l1_health",
        members,
        rows,
        snap=None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert out["warm_to_hot_member_count"] == 0
    assert out["amount"] == 1e8
