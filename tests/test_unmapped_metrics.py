from datetime import date

from scripts.taxonomy.unmapped import compute_unmapped_metrics, parse_em_list_date


def test_parse_f26_yyyymmdd_and_ms():
    assert parse_em_list_date("20240105") == date(2024, 1, 5)
    # Numeric YYYYMMDD (pandas/EM clist to_dict) — not Unix seconds → 1970.
    assert parse_em_list_date(20240105) == date(2024, 1, 5)
    assert parse_em_list_date(20240105.0) == date(2024, 1, 5)
    # 2024-01-05 00:00 Asia/Shanghai
    assert parse_em_list_date(1704384000000) == date(2024, 1, 5)
    assert parse_em_list_date(None) is None


def test_unmapped_count_formula(tmp_path, monkeypatch):
    first_seen = tmp_path / "unmapped_first_seen.json"
    first_seen.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: ["000001.SZ"],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    clist = [
        {"ts_code": "000001.SZ", "f26": "20200101"},
        {"ts_code": "000002.SZ", "f26": "20200101"},
    ]
    m = compute_unmapped_metrics(
        clist_rows=clist,
        session_asof=date(2024, 1, 10),
        first_seen_path=str(first_seen),
    )
    assert m.clist_fetch == "ok"
    assert m.unmapped_count == 1
    # 2020 list_date → many trading days ≥ 3
    assert m.ipo_unmapped_alert_count == 1


def test_ipo_alert_via_f26_not_first_seen(tmp_path, monkeypatch):
    """f26 must drive IPO≥3; empty first_seen must not be required."""
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.trading_days_inclusive",
        lambda a, b: [d for d in [
            date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
        ] if a <= d <= b],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: [],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    first_seen = tmp_path / "fs.json"
    first_seen.write_text("{}", encoding="utf-8")
    m = compute_unmapped_metrics(
        clist_rows=[{"ts_code": "000002.SZ", "f26": "20240102"}],  # or ms 1704124800000
        session_asof=date(2024, 1, 5),
        first_seen_path=str(first_seen),
    )
    # inclusive [01-02 .. 01-05] = 4 ≥ 3
    assert m.ipo_unmapped_alert_count == 1


def test_first_seen_writes_session_asof(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.trading_days_inclusive",
        lambda a, b: [a] if a == b else [],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: [],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    first_seen = tmp_path / "fs.json"
    first_seen.write_text("{}", encoding="utf-8")
    asof = date(2024, 1, 10)
    compute_unmapped_metrics(
        clist_rows=[{"ts_code": "000003.SZ", "f26": None}],
        session_asof=asof,
        first_seen_path=str(first_seen),
    )
    data = json.loads(first_seen.read_text(encoding="utf-8"))
    assert data["000003.SZ"] == "2024-01-10"


def test_ipo_alert_first_seen(tmp_path, monkeypatch):
    # Use a tiny synthetic calendar: 2024-01-02,03,04,05 (weekdays)
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.trading_days_inclusive",
        lambda a, b: [d for d in [
            date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
        ] if a <= d <= b],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: [],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    first_seen = tmp_path / "fs.json"
    first_seen.write_text('{"000002.SZ": "2024-01-02"}', encoding="utf-8")
    m = compute_unmapped_metrics(
        clist_rows=[{"ts_code": "000002.SZ", "f26": None}],
        session_asof=date(2024, 1, 5),
        first_seen_path=str(first_seen),
    )
    # inclusive [01-02 .. 01-05] = 4 trading days ≥ 3
    assert m.ipo_unmapped_alert_count == 1


def test_clist_fail_returns_null_counts(tmp_path, monkeypatch):
    first_seen = tmp_path / "fs.json"
    first_seen.write_text("{}", encoding="utf-8")

    def _boom(**kwargs):
        raise RuntimeError("em down")

    m = compute_unmapped_metrics(
        clist_fetch=_boom,
        session_asof=date(2024, 1, 10),
        first_seen_path=str(first_seen),
    )
    assert m.clist_fetch == "fail"
    assert m.unmapped_count is None
    assert m.ipo_unmapped_alert_count is None


def test_yaml_quarantine_not_in_unmapped_count(tmp_path, monkeypatch):
    """YAML-only quarantine / null-sw_l2 is not |clist−mapped|."""
    first_seen = tmp_path / "fs.json"
    first_seen.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: ["000001.SZ"],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: {"000099.SZ"},  # in YAML quarantine, not necessarily in clist
    )
    m = compute_unmapped_metrics(
        clist_rows=[
            {"ts_code": "000001.SZ", "f26": "20200101"},
            {"ts_code": "000002.SZ", "f26": "20200101"},
        ],
        session_asof=date(2024, 1, 10),
        first_seen_path=str(first_seen),
    )
    assert m.unmapped_count == 1  # only 000002
    assert m.yaml_quarantine_size == 1
