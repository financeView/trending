# tests/test_sync_status.py
from __future__ import annotations

import json
import os

from scripts.common.sync_status import (
    check_sync_complete_for_fill,
    read_sync_status,
    write_sync_status,
)


def test_false_status_fails_check(tmp_path):
    p = tmp_path / "sync_status.json"
    write_sync_status(sync_complete=False, session_asof="2024-06-10", path=p)
    assert check_sync_complete_for_fill(fill_asof="2024-06-10", status_path=p) == 1


def test_complete_tip_authorizes_same_and_earlier_fill(tmp_path):
    p = tmp_path / "sync_status.json"
    write_sync_status(sync_complete=True, session_asof="2024-06-12", path=p)
    assert check_sync_complete_for_fill(fill_asof="2024-06-12", status_path=p) == 0
    assert check_sync_complete_for_fill(fill_asof="2024-06-10", status_path=p) == 0


def test_stale_tip_rejects_later_fill(tmp_path):
    p = tmp_path / "sync_status.json"
    write_sync_status(sync_complete=True, session_asof="2024-06-10", path=p)
    assert check_sync_complete_for_fill(fill_asof="2024-06-12", status_path=p) == 1


def test_missing_file_fails(tmp_path):
    p = tmp_path / "missing.json"
    assert check_sync_complete_for_fill(fill_asof="2024-06-10", status_path=p) == 1


def test_invalid_json_fails(tmp_path):
    p = tmp_path / "sync_status.json"
    p.write_text("{not json", encoding="utf-8")
    assert read_sync_status(p) is None
    assert check_sync_complete_for_fill(fill_asof="2024-06-10", status_path=p) == 1


def test_missing_session_asof_fails(tmp_path):
    p = tmp_path / "sync_status.json"
    p.write_text(
        json.dumps({"sync_complete": True, "elapsed_min": 0.0, "written_at": "x"}),
        encoding="utf-8",
    )
    assert check_sync_complete_for_fill(fill_asof="2024-06-10", status_path=p) == 1
    p.write_text(
        json.dumps(
            {
                "sync_complete": True,
                "session_asof": None,
                "elapsed_min": 0.0,
                "written_at": "x",
            }
        ),
        encoding="utf-8",
    )
    assert check_sync_complete_for_fill(fill_asof="2024-06-10", status_path=p) == 1


def test_env_bypass(tmp_path, monkeypatch):
    p = tmp_path / "missing.json"
    monkeypatch.delenv("TRENDING_ALLOW_INCOMPLETE_FILL", raising=False)
    assert check_sync_complete_for_fill(fill_asof="2024-06-10", status_path=p) == 1
    monkeypatch.setenv("TRENDING_ALLOW_INCOMPLETE_FILL", "1")
    assert check_sync_complete_for_fill(fill_asof="2024-06-10", status_path=p) == 0


def test_atomic_write_roundtrip(tmp_path):
    p = tmp_path / "sync_status.json"
    write_sync_status(
        sync_complete=True,
        session_asof="2024-01-02",
        elapsed_min=1.5,
        path=p,
        written_at="2024-01-02T00:00:00Z",
    )
    data = read_sync_status(p)
    assert data is not None
    assert data["sync_complete"] is True
    assert data["session_asof"] == "2024-01-02"
    assert data["elapsed_min"] == 1.5
