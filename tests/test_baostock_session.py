"""BaoStock session: one login for a batch; periodic / on-error re-login."""
from datetime import date
from types import SimpleNamespace

from scripts.common.bars import BaostockSession, baostock_session, fetch_baostock_flags


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


def _install_fake_bs(monkeypatch, *, fail_queries=None):
    calls = {"login": 0, "logout": 0, "query": 0}
    fail_queries = set(fail_queries or [])

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
            if calls["query"] in fail_queries:
                raise RuntimeError("session dead")
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
    return calls


def test_baostock_session_login_logout_once(monkeypatch):
    calls = _install_fake_bs(monkeypatch)

    with baostock_session() as sess:
        assert isinstance(sess, BaostockSession)
        a = fetch_baostock_flags(
            "000001.SZ",
            date(2024, 1, 1),
            date(2024, 1, 10),
            session=sess,
        )
        b = fetch_baostock_flags(
            "000002.SZ",
            date(2024, 1, 1),
            date(2024, 1, 10),
            session=sess,
        )

    assert calls["login"] == 1
    assert calls["logout"] >= 1  # exit logout (+ optional pre-login logout)
    assert calls["query"] == 2
    assert len(a) == 2
    assert a[0][2] == 0 and a[1][2] == 1
    assert a[1][3] == 1
    assert len(b) == 2


def test_baostock_session_relogin_on_error(monkeypatch):
    calls = _install_fake_bs(monkeypatch, fail_queries={1})

    with baostock_session() as sess:
        fetch_baostock_flags(
            "000001.SZ",
            date(2024, 1, 1),
            date(2024, 1, 10),
            session=sess,
        )

    # enter login + relogin after first query failure
    assert calls["login"] >= 2
    assert calls["query"] >= 2


def test_baostock_session_periodic_relogin(monkeypatch):
    calls = _install_fake_bs(monkeypatch)

    with BaostockSession(relogin_every=2) as sess:
        for i in range(3):
            fetch_baostock_flags(
                "00000%d.SZ" % i,
                date(2024, 1, 1),
                date(2024, 1, 10),
                session=sess,
            )

    # initial + after every 2 queries (before 3rd)
    assert calls["login"] >= 2


def test_fetch_manage_session_true_logs_in_per_call(monkeypatch):
    calls = _install_fake_bs(monkeypatch)

    fetch_baostock_flags(
        "000001.SZ", date(2024, 1, 1), date(2024, 1, 10), manage_session=True
    )
    fetch_baostock_flags(
        "000002.SZ", date(2024, 1, 1), date(2024, 1, 10), manage_session=True
    )
    assert calls["login"] == 2
    assert calls["logout"] >= 2
