from pathlib import Path


def test_actions_live_shadow_before_single_db_commit():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    daily = text.index("python scripts/daily_run.py")
    shadow = text.index("python scripts/eval/live_shadow_step.py --from-heartbeat")
    commit = text.index("git add data/trend.db data/heartbeat.json")
    issues = text.index("python scripts/issues/update_l1_issues.py")
    assert daily < shadow < commit < issues
    between = text[daily:commit]
    assert "continue-on-error" not in between
    assert text.count("git commit -m") == 1
    assert "continue-on-error: true" in text.split("Update L1 / Radar Issues", 1)[1]
