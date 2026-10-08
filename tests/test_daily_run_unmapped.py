from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class _UM:
    unmapped_count: int | None
    ipo_unmapped_alert_count: int | None
    yaml_quarantine_size: int
    clist_fetch: str


def test_asof_run_meta_unmapped_not_literal_zero(tmp_path, monkeypatch):
    from scripts.daily_run import _run_meta_unmapped_fields

    asof = date(2024, 1, 10)
    um = _UM(3, 1, 0, "ok")
    fields = _run_meta_unmapped_fields(D=asof, session_asof=asof, um=um)
    assert fields["unmapped_count"] == 3
    prior = _run_meta_unmapped_fields(
        D=date(2024, 1, 9), session_asof=asof, um=um, prior_unmapped_count=9
    )
    assert prior["unmapped_count"] == 9  # not today's 3


def test_warn_appends_taxonomy():
    from scripts.daily_run import _append_taxonomy_warn

    # Match process_day: "passed" is cleared to "" before warn append
    assert (
        _append_taxonomy_warn(
            "limit_coverage_asof<0.80",
            ipo_alert=1,
            taxonomy_fetch="ok",
            clist_fetch="ok",
        )
        == "limit_coverage_asof<0.80; taxonomy: ipo_unmapped_alert=1"
    )
    assert "taxonomy_fetch=fail" in _append_taxonomy_warn(
        "", ipo_alert=0, taxonomy_fetch="fail", clist_fetch="ok"
    )
    assert "taxonomy_fetch=push_fail" in _append_taxonomy_warn(
        "", ipo_alert=0, taxonomy_fetch="push_fail", clist_fetch="ok"
    )
    # bare unmapped_count>0 must NOT warn (design §2)
    assert (
        _append_taxonomy_warn(
            "",
            ipo_alert=0,
            taxonomy_fetch="ok",
            clist_fetch="ok",
            unmapped_count=99,
        )
        == ""
    )


def test_git_sha_prefers_taxonomy_head_then_github_sha(monkeypatch):
    from scripts.daily_run import _resolve_git_sha

    monkeypatch.setenv("TAXONOMY_HEAD_SHA", "deadbeef")
    monkeypatch.setenv("GITHUB_SHA", "checkout1")
    assert _resolve_git_sha() == "deadbeef"

    monkeypatch.delenv("TAXONOMY_HEAD_SHA", raising=False)
    monkeypatch.setenv("GITHUB_SHA", "checkout1")
    # push_fail / unpushed: keep checkout SHA — never fall through to local HEAD
    assert _resolve_git_sha() == "checkout1"


def test_asof_status_ignores_ipo_alert():
    """Soft gate: status comes only from evaluate_ok; IPO only affects warn text."""
    from scripts.common.coverage import CoverageMetrics, evaluate_ok
    from scripts.daily_run import _compose_asof_status_and_warn

    m = CoverageMetrics(
        bar_coverage=1.0,
        computable_coverage=1.0,
        limit_coverage_asof=1.0,
        mapped_sync_coverage=1.0,
    )
    asof = date(2024, 1, 10)
    decision = evaluate_ok(asof, asof, m)
    status, warn = _compose_asof_status_and_warn(
        decision,
        ipo_alert=2,
        taxonomy_fetch="ok",
        clist_fetch="ok",
    )
    assert status == "ok"
    assert decision.status == "ok"
    assert "ipo_unmapped_alert=2" in warn


def test_write_heartbeat_preserves_taxonomy(tmp_path):
    import json
    from scripts.common.db import write_heartbeat

    hb = tmp_path / "heartbeat.json"
    hb.write_text(
        json.dumps({"taxonomy": {"taxonomy_fetch": "ok", "unmapped_count": 3}}),
        encoding="utf-8",
    )
    write_heartbeat({"job": "daily_run", "status": "ok"}, path=str(hb))
    data = json.loads(hb.read_text(encoding="utf-8"))
    assert data["taxonomy"]["taxonomy_fetch"] == "ok"
    assert data["daily_run"]["status"] == "ok"
