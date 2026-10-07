"""Spec §5.1: 凉/寒 can coexist with high peer RS (not collinear with T)."""
from scripts.metrics.peer_rs import assign_peer_rs


def test_colinearity_story():
    """Cool/cold temperature with top-of-peer RS_raw → RS >= 80."""
    rows = [
        {"ts_code": "cool", "T": "凉", "RS_raw": 0.99, "RS": None},
        {"ts_code": "hot_a", "T": "热", "RS_raw": 0.10, "RS": None},
        {"ts_code": "hot_b", "T": "热", "RS_raw": 0.20, "RS": None},
        {"ts_code": "warm", "T": "温", "RS_raw": 0.30, "RS": None},
        {"ts_code": "flat", "T": "平", "RS_raw": 0.40, "RS": None},
        {"ts_code": "cold", "T": "寒", "RS_raw": 0.50, "RS": None},
    ]
    assign_peer_rs(rows, eligible=lambda r: r.get("RS_raw") is not None)
    cool = next(r for r in rows if r["T"] == "凉")
    assert cool["T"] in {"凉", "寒"}
    assert cool["RS"] is not None and cool["RS"] >= 80
