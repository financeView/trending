"""BaoStock session: one login for a batch of flag queries."""
from datetime import date
from types import SimpleNamespace

from scripts.common.bars import baostock_session, fetch_baostock_flags


class _FakeRs:
    error_code = "0"

    def __init__(self, rows):
        self._rows = list(rows)
        self._i = 0

    def next(self):
        if self._i >= len(self._rows):
            return False
        self._i += 1
        return True

    def get_row_data(self):
        return self._rows[self._i - 1]


def test_baostock_session_login_logout_once(monkeypatch):
    calls = {"login": 0, "logout": 0, "query": 0}

    class FakeBs:
        @staticmethod
        def login():
            calls["login"] += 1
            return SimpleNamespace(error_code="0", error_msg="")

        @staticmethod
        def logout():
            calls["logout"] += 1

        @staticmethod
        def query_history_k_data_plus(*_a, **_k):
            calls["query"] += 1
            return _FakeRs(
                [
                    ["2024-01-08", "sz.000001", "1", "0"],
                    ["2024-01-09", "sz.000001", "0", "1"],
                ]
            )

    monkeypatch.setitem(__import__("sys").modules, "baostock", FakeBs)
    monkeypatch.setattr(
        "scripts.common.http.time.sleep", lambda *_a, **_k: None
    )

    with baostock_session():
        a = fetch_baostock_flags(
            "000001.SZ",
            date(2024, 1, 1),
            date(2024, 1, 10),
            manage_session=False,
        )
        b = fetch_baostock_flags(
            "000002.SZ",
            date(2024, 1, 1),
            date(2024, 1, 10),
            manage_session=False,
        )

    assert calls["login"] == 1
    assert calls["logout"] == 1
    assert calls["query"] == 2
    assert len(a) == 2
    assert a[0][2] == 0 and a[1][2] == 1  # suspended
    assert a[1][3] == 1  # ST
    assert len(b) == 2


def test_fetch_manage_session_true_logs_in_per_call(monkeypatch):
    calls = {"login": 0, "logout": 0}

    class FakeBs:
        @staticmethod
        def login():
            calls["login"] += 1
            return SimpleNamespace(error_code="0", error_msg="")

        @staticmethod
        def logout():
            calls["logout"] += 1

        @staticmethod
        def query_history_k_data_plus(*_a, **_k):
            return _FakeRs([["2024-01-08", "sz.000001", "1", "0"]])

    monkeypatch.setitem(__import__("sys").modules, "baostock", FakeBs)
    monkeypatch.setattr(
        "scripts.common.http.time.sleep", lambda *_a, **_k: None
    )

    fetch_baostock_flags(
        "000001.SZ", date(2024, 1, 1), date(2024, 1, 10), manage_session=True
    )
    fetch_baostock_flags(
        "000002.SZ", date(2024, 1, 1), date(2024, 1, 10), manage_session=True
    )
    assert calls["login"] == 2
    assert calls["logout"] == 2
