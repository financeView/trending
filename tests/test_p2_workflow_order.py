import re
from pathlib import Path

_GATE = (
    "success() && steps.sync.outputs.sync_complete == 'true' "
    "&& steps.sync.outputs.run_deferred != 'true'"
)


def test_actions_live_shadow_before_single_db_commit():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    daily = text.index("python scripts/daily_run.py")
    shadow = text.index("python scripts/eval/live_shadow_step.py --from-heartbeat")
    commit = text.index("git add data/trend.db data/heartbeat.json")
    issues = text.index("python scripts/issues/update_l1_issues.py")
    assert daily < shadow < commit < issues
    between = text[daily:commit]
    assert "continue-on-error" not in between
    assert "id: sync" in text
    assert "--from-universe" not in text
    assert "timeout-minutes: 360" in text
    assert "only_date requires date" in text
    assert text.count("git commit -m") == 1
    assert "continue-on-error: true" in text.split("Update L1 / Radar Issues", 1)[1]
    # All four post-sync steps must restatement success + sync_complete + !run_deferred
    for marker in (
        "name: daily_run",
        "name: live_shadow",
        "name: Commit trend.db",
        "name: Update L1 / Radar Issues",
    ):
        idx = text.index(marker)
        chunk = text[idx : idx + 400]
        assert _GATE in chunk, marker
    # Catch-up / cron: Issues from heartbeat; only_date may still pass --date
    issues_chunk = text[text.index("name: Update L1 / Radar Issues") :]
    assert "--from-heartbeat" in issues_chunk
    assert 'ONLY" = "true"' in issues_chunk
    assert "--date" in issues_chunk


def test_workflow_only_date_shadow_uses_asof_not_heartbeat():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    m = re.search(
        r"- name: live_shadow\n.*?run: \|(.*?)(?=\n      - name:|\n\njobs:|\Z)",
        text,
        re.S,
    )
    assert m, "live_shadow step missing"
    block = m.group(1)
    # only_date branch must pin asof
    assert 'live_shadow_step.py --asof "$DATE"' in block or \
           "live_shadow_step.py --asof \"$DATE\"" in block
    # Extract the then-branch between ONLY=true and else
    then = re.search(
        r'if \[ "\$ONLY" = "true" \].*?\n(.*?)else\n',
        block,
        re.S,
    )
    assert then, "only_date if-branch missing in live_shadow"
    assert "--from-heartbeat" not in then.group(1)
    assert "--from-heartbeat" in block  # else/cron path still present
