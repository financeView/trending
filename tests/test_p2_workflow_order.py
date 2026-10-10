import re
from pathlib import Path


def _metrics_block(text: str) -> str:
    m = re.search(r"^  metrics:\n(.*?)(?=^  [a-z]|\Z)", text, re.M | re.S)
    assert m, "metrics job missing"
    return m.group(1)


def _sync_block(text: str) -> str:
    m = re.search(r"^  sync:\n(.*?)(?=^  metrics:|\Z)", text, re.M | re.S)
    assert m, "sync job missing"
    return m.group(1)


def test_workflow_has_sync_and_metrics_jobs():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    assert re.search(r"^  sync:\s*$", text, re.M)
    assert re.search(r"^  metrics:\s*$", text, re.M)
    assert "needs: sync" in text or "needs: [sync]" in text
    # Ignore # comments; gate must not appear in executable YAML
    body = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "run_deferred" not in body
    assert "--time-budget-min" not in body
    assert "needs.sync.outputs.sync_complete" in text
    assert text.count("bars-${{ github.run_id }}") >= 2
    assert text.count("timeout-minutes: 360") >= 2
    met = _metrics_block(text)
    assert "ref:" in met or "repository.default_branch" in met
    assert "cache-hit" in met
    assert "BARS_SOURCE" in text
    assert "restore-keys:" not in met


def test_actions_unit_tests_then_taxonomy_then_sync():
    """Spec D/F: Unit tests → Refresh taxonomy YAML → Sync mapped-universe bars (sync job)."""
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    sync = _sync_block(text)
    unit = sync.index("name: Unit tests")
    taxonomy = sync.index("name: Refresh taxonomy YAML")
    bars = sync.index("name: Sync mapped-universe bars")
    assert unit < taxonomy < bars
    tax_chunk = sync[taxonomy:bars]
    assert "continue-on-error" not in tax_chunk
    assert "only_date requires date" in sync
    assert "sync_incomplete" in sync


def test_metrics_ordered_daily_shadow_commit_issues():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    met = _metrics_block(text)
    daily = met.index("python scripts/daily_run.py")
    # only_date may use --asof; cron uses --from-heartbeat — either shadow line is fine for order
    shadow = met.index("live_shadow_step.py")
    commit = met.index("git add data/trend.db data/heartbeat.json")
    issues = met.index("update_l1_issues.py")
    assert daily < shadow < commit < issues
    assert met.count("git commit -m") == 1
    assert "continue-on-error: true" in met.split("Update L1 / Radar Issues", 1)[1]
    between = met[daily:commit]
    assert "continue-on-error" not in between
    assert "--from-universe" not in text


def test_workflow_only_date_shadow_uses_asof_not_heartbeat():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    met = _metrics_block(text)
    m = re.search(
        r"- name: live_shadow\n.*?run: \|(.*?)(?=\n      - name:|\Z)",
        met,
        re.S,
    )
    assert m, "live_shadow step missing"
    block = m.group(1)
    assert 'live_shadow_step.py --asof "$DATE"' in block or \
           "live_shadow_step.py --asof \"$DATE\"" in block
    then = re.search(
        r'if \[ "\$ONLY" = "true" \].*?\n(.*?)else\n',
        block,
        re.S,
    )
    assert then, "only_date if-branch missing in live_shadow"
    assert "--from-heartbeat" not in then.group(1)
    assert "--from-heartbeat" in block
