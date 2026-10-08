from scripts.metrics.peer_rs import assign_peer_rs, stock_peer_eligible


def test_peer_isolation_stock_vs_l2():
    stocks = [
        {"ts_code": "A", "RS_raw": 0.1, "RS": None},
        {"ts_code": "B", "RS_raw": 0.9, "RS": None},
    ]
    l2 = [{"code": "370100", "RS_raw": 0.1, "T": "热", "RS": None}]
    assign_peer_rs(stocks, eligible=lambda r: r.get("RS_raw") is not None)
    assign_peer_rs(l2, eligible=lambda r: r.get("T") is not None and r.get("RS_raw") is not None)
    assert stocks[0]["RS"] == 0 and stocks[1]["RS"] == 100
    assert l2[0]["RS"] is None  # n<=1


def test_peer_isolation_three_universes():
    """local_stock / local_l2 / local_l1 peer scores ignore the other universes."""
    stocks = [
        {"ts_code": "s_lo", "RS_raw": 0.01, "RS": None},
        {"ts_code": "s_hi", "RS_raw": 0.99, "RS": None},
    ]
    # Distinct scale from stocks — if mixed into one peer, ranks would change.
    l2 = [
        {"code": "l2_lo", "T": "热", "RS_raw": 10.0, "RS": None},
        {"code": "l2_hi", "T": "温", "RS_raw": 20.0, "RS": None},
    ]
    l1 = [
        {"code": "l1_lo", "T": "平", "RS_raw": 100.0, "RS": None},
        {"code": "l1_hi", "T": "凉", "RS_raw": 200.0, "RS": None},
    ]
    assign_peer_rs(stocks, eligible=lambda r: r.get("RS_raw") is not None)
    assign_peer_rs(
        l2, eligible=lambda r: r.get("T") is not None and r.get("RS_raw") is not None
    )
    assign_peer_rs(
        l1, eligible=lambda r: r.get("T") is not None and r.get("RS_raw") is not None
    )
    assert stocks[0]["RS"] == 0 and stocks[1]["RS"] == 100
    assert l2[0]["RS"] == 0 and l2[1]["RS"] == 100
    assert l1[0]["RS"] == 0 and l1[1]["RS"] == 100


def test_st_not_eligible():
    row = {
        "ts_code": "000001.SZ",
        "RS_raw": 1.0,
        "hard_frozen": True,
        "_is_suspended": False,
    }
    assert stock_peer_eligible(row, quarantine=set()) is False


def test_quarantine_not_eligible():
    row = {
        "ts_code": "000002.SZ",
        "RS_raw": 1.0,
        "hard_frozen": False,
        "_is_suspended": False,
    }
    assert stock_peer_eligible(row, quarantine={"000002.SZ"}) is False


def test_halt_not_eligible():
    row = {
        "ts_code": "000001.SZ",
        "RS_raw": 1.0,
        "hard_frozen": False,
        "_is_suspended": True,
    }
    assert stock_peer_eligible(row, quarantine=set()) is False
