# Spec A Ops Daily-Run Hemostasis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Soften asof limit gate to `ok`+`warn` with `last_ok` advance; fix nested heartbeat readers; pin shadow date on Actions `only_date`.

**Architecture:** Change only `evaluate_ok` predicate + `run_meta.warn` persistence (keep coverage=0 on EM fail). Share one `_heartbeat_job_view` for Issues/shadow/skip. Workflow branches shadow like Issues already does for `--date`.

**Tech Stack:** Python 3.11, sqlite3, pytest, GitHub Actions YAML.

## Global Constraints

- Spec: [`2026-10-07-ops-daily-run-hemostasis-design.md`](../specs/2026-10-07-ops-daily-run-hemostasis-design.md) (CR×2 patched; implement against that + market-data §7.2 v1.2)
- Authority for ok predicate: market-data contract (already revised in-repo); do not re-harden limit→partial
- Soft ok: `status=ok`, `reason=limit_coverage_asof<0.80`, `last_ok` advances; mapped/bar/computable still hard-partial
- Do **not** change clist catch→0-row→coverage=0; no fake limits; no auto re-fetch; no third status
- Heartbeat: `days`/`statuses` are parallel **lists** under `daily_run`; readers use job view
- `only_date` shadow: **only** `--asof "$DATE"` (never also `--from-heartbeat`)
- Do not commit `data/cache/trade_dates.json` noise; heartbeat/trend.db only via Actions chore commits
- **Before Task 1 code:** commit already-edited market-data + YAML universe §3 + this plan + Spec A (docs-only), so authority docs are on the branch

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/common/coverage.py` | `OK_PREDICATE_VERSION=v1.2`; soft limit in `evaluate_ok` |
| `scripts/daily_run.py` | Persist warn when `ok` and `reason != "passed"` |
| `scripts/issues/update_l1_issues.py` | `_heartbeat_job_view`; fix `trade_date_from_heartbeat` + `live_publish_allowed` skip |
| `scripts/eval/live_shadow_step.py` | `heartbeat_asof_dates` via same view (import from issues module) |
| `.github/workflows/daily-trend.yml` | `only_date` → shadow `--asof` |
| `tests/test_p0_core.py` | Delete old asof-limit→partial; soft ok; rewrite queue/resume; named soft→last_ok |
| `tests/test_daily_run_metrics_wire.py` | Flip `test_asof_low_limit_*`; warn on ok |
| `tests/test_p05_data_wiring.py` | Flip `test_process_day_uses_real_coverage` clear-limits → soft ok |
| `tests/test_issue_heartbeat_gate.py` | Nested heartbeat + `heartbeat_asof_dates` |
| `tests/test_live_shadow_gate.py` | Keep flat catch-up green after nested view |
| `tests/test_p2_workflow_order.py` (or new) | Parse `live_shadow` run block |
| `todo.md` / specs | Mark Spec A done when green |

```text
Task 0 (docs authority commit)
Task 1 (evaluate_ok soft) ─► Task 2 (warn + wire/last_ok/queue)
Task 3 (heartbeat view) ───► Task 4 (workflow only_date)  [∥ Task 1 OK]
         └──────────────────► Task 5 (done-when)
```

---

### Task 0: Commit design-authority docs (before code)

**Files:**
- `docs/superpowers/specs/2026-10-01-market-data-contract-design.md`
- `docs/superpowers/specs/2026-10-05-sw-yaml-universe-design.md`
- `docs/superpowers/specs/2026-10-07-ops-daily-run-hemostasis-design.md`
- `docs/superpowers/plans/2026-10-07-ops-daily-run-hemostasis.md`
- `todo.md` (route pointer only; status still 进行中 until Task 5)

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/specs/2026-10-01-market-data-contract-design.md \
  docs/superpowers/specs/2026-10-05-sw-yaml-universe-design.md \
  docs/superpowers/specs/2026-10-07-ops-daily-run-hemostasis-design.md \
  docs/superpowers/plans/2026-10-07-ops-daily-run-hemostasis.md \
  todo.md
git commit -m "$(cat <<'EOF'
docs: Spec A ops hemostasis + market-data v1.2 limit soft-ok

EOF
)"
```

---

### Task 1: Soft limit in `evaluate_ok`

**Files:**
- Modify: `scripts/common/coverage.py`
- Test: `tests/test_p0_core.py`

**Interfaces:**
- Produces: `OK_PREDICATE_VERSION == "v1.2"`
- Produces: when `D == asof` and other gates pass and `limit_coverage_asof < 0.80` → `OkDecision(ok=True, status="ok", reason="limit_coverage_asof<0.80", apply_limit_gate=True)`
- Produces: when limits ok → `reason="passed"`

- [ ] **Step 1: Failing tests — delete old name**

**Delete** `test_ok_asof_requires_limits` entirely (do not leave both names). Add:

```python
def test_ok_asof_low_limit_is_soft_ok():
    asof = date(2024, 1, 10)
    m = CoverageMetrics(
        bar_coverage=0.95,
        computable_coverage=0.6,
        limit_coverage_asof=0.5,
        mapped_sync_coverage=1.0,
    )
    d = evaluate_ok(asof, asof, m)
    assert d.ok and d.status == "ok"
    assert "limit_coverage" in d.reason
    assert d.apply_limit_gate is True

def test_ok_asof_with_limits_reason_passed():
    asof = date(2024, 1, 10)
    m = CoverageMetrics(
        bar_coverage=0.95,
        computable_coverage=0.6,
        limit_coverage_asof=0.85,
        mapped_sync_coverage=1.0,
    )
    d = evaluate_ok(asof, asof, m)
    assert d.ok and d.reason == "passed"
    assert d.apply_limit_gate is True
```

Keep history-day limit=0 → ok with `apply_limit_gate is False`.

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_p0_core.py::test_ok_asof_low_limit_is_soft_ok -v
```

- [ ] **Step 3: Implement**

```python
if apply_limit and metrics.limit_coverage_asof < LIMIT_COVERAGE_ASOF_MIN:
    return OkDecision(
        True,
        "ok",
        "limit_coverage_asof<%.2f" % LIMIT_COVERAGE_ASOF_MIN,
        True,
    )
```

Set `OK_PREDICATE_VERSION = "v1.2"`.

- [ ] **Step 4: PASS** `test_ok_asof_low_limit_is_soft_ok`, `test_ok_asof_with_limits_reason_passed`, history-day limit tests. Confirm **no** leftover `test_ok_asof_requires_limits`.

- [ ] **Step 5: Commit**

```bash
git add scripts/common/coverage.py tests/test_p0_core.py
git commit -m "$(cat <<'EOF'
feat(coverage): soft-ok asof when limit_coverage below min (v1.2)

EOF
)"
```

---

### Task 2: Persist warn on soft ok + flip **all** limit→partial wire tests

**Files:**
- Modify: `scripts/daily_run.py` (run_meta `warn=` assignment)
- Modify: `tests/test_daily_run_metrics_wire.py`
- Modify: `tests/test_p0_core.py` (`test_queue_stops_and_resume_from_gap` + **new** soft last_ok test)
- Modify: `tests/test_p05_data_wiring.py` (`test_process_day_uses_real_coverage`)

**Interfaces:**
- Consumes: Task 1 `OkDecision.reason`
- Produces: soft ok → non-empty `run_meta.warn`; `last_ok` includes that asof day; queue no longer stops on limit-only soft ok

**Grep before claiming green:** `rg 'partial' tests -g '*.py'` for asof/limit clears — flip every **limit-only→partial** assert (known: wire + p05). Do **not** flip `live_allowed(..., status=partial)` tests.

- [ ] **Step 1: Failing wire test**

Rename `test_asof_low_limit_run_meta_partial` → `test_asof_low_limit_run_meta_ok_with_warn`.  
**Keep the existing scaffold** (`_patch_run`, `_seed_uptrend(..., with_limits=False)`, `get_conn`, same `D`). Only change assertions:

```python
def test_asof_low_limit_run_meta_ok_with_warn(tmp_path, monkeypatch):
    from scripts.common import db as dbmod
    from scripts.daily_run import process_day
    # ... identical setup to former test_asof_low_limit_run_meta_partial ...
    st = process_day(D, D, bars_path=bars_path)
    assert st == "ok"
    tconn = get_conn()
    status, warn, ver = tconn.execute(
        "SELECT status, warn, ok_predicate_version FROM run_meta WHERE trade_date=?",
        (D.isoformat(),),
    ).fetchone()
    assert status == "ok"
    assert "limit_coverage" in (warn or "")
    assert ver == "v1.2"
    assert dbmod.last_ok_trade_date(tconn) == D.isoformat()
    tconn.close()
```

Also flip `tests/test_p05_data_wiring.py::test_process_day_uses_real_coverage`: after clearing limits, expect `st2 == "ok"` and `warn` contains `limit_coverage` (not `partial`). Keep the first half (`st == "ok"` with limits present).

- [ ] **Step 2: Run — FAIL** (`partial` and/or empty warn)

- [ ] **Step 3: Implement warn persistence**

```python
"warn": (
    decision.reason
    if decision.reason and decision.reason != "passed"
    else ""
),
```

- [ ] **Step 4: Rewrite queue + named soft last_ok (mandatory)**

1. **`test_queue_stops_and_resume_from_gap`:** replace asof `limit_coverage_asof=0.1` gap with **hard** failure (`mapped_sync_coverage=0.5`, other fields high) → `process_day(asof)=="partial"`, `build_queue` starts at asof, contiguous `last_ok` before asof.  
2. **Add named** `test_asof_soft_limit_advances_last_ok` (not optional): inject metrics with only low limit → `process_day=="ok"` and `last_ok_trade_date == asof.isoformat()`.

- [ ] **Step 5: PASS**

```bash
python3 -m pytest \
  tests/test_daily_run_metrics_wire.py::test_asof_low_limit_run_meta_ok_with_warn \
  tests/test_p05_data_wiring.py::test_process_day_uses_real_coverage \
  tests/test_p0_core.py::test_queue_stops_and_resume_from_gap \
  tests/test_p0_core.py::test_asof_soft_limit_advances_last_ok \
  tests/test_p0_core.py -q
```

- [ ] **Step 6: Commit**

```bash
git add scripts/daily_run.py tests/test_daily_run_metrics_wire.py \
  tests/test_p0_core.py tests/test_p05_data_wiring.py
git commit -m "$(cat <<'EOF'
fix(daily_run): persist warn on soft-ok; advance last_ok past low limits

EOF
)"
```

---

### Task 3: Nested heartbeat job view

**Files:**
- Modify: `scripts/issues/update_l1_issues.py`
- Modify: `scripts/eval/live_shadow_step.py`
- Test: `tests/test_issue_heartbeat_gate.py`
- Regression: `tests/test_live_shadow_gate.py` (flat `days` catch-up — must stay green)

**Interfaces:**
- Produces `_heartbeat_job_view(data: dict) -> dict` (one implementation; shadow imports it)
- All of: `trade_date_from_heartbeat`, `live_publish_allowed` skip, `heartbeat_asof_dates` read via view
- Skip gate: `view.get("status")=="skip"` and match `trade_date` to `view.get("date") or view.get("asof")` (prod skip heartbeat uses `date` under nested job)

- [ ] **Step 1: Failing tests in `test_issue_heartbeat_gate.py` (full scaffolds)**

```python
def _write_nested(path, *, status="ok", asof="2024-01-10",
                  days=None, statuses=None, date=None):
    days = days or ["2024-01-08", "2024-01-10"]
    statuses = statuses or ["ok", "ok"]
    job = {"status": status, "asof": asof, "days": days, "statuses": statuses}
    if date is not None:
        job["date"] = date
    path.write_text(
        json.dumps({"updated_at": "t", "daily_run": job}),
        encoding="utf-8",
    )

def test_nested_heartbeat_trade_date(tmp_path):
    path = tmp_path / "heartbeat.json"
    _write_nested(path)
    td, reason = trade_date_from_heartbeat(str(path))
    assert reason == "ok" and td == "2024-01-10"

def test_nested_heartbeat_asof_dates_full_prefix(tmp_path):
    from scripts.eval.live_shadow_step import heartbeat_asof_dates
    path = tmp_path / "heartbeat.json"
    _write_nested(path)
    dates, reason = heartbeat_asof_dates(str(path))
    assert reason == "ok"
    assert dates == ["2024-01-08", "2024-01-10"]

def test_nested_heartbeat_skip_blocks_publish(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "trend.db"))
    conn = get_conn()
    init_schema(conn)
    conn.execute(
        """INSERT INTO run_meta (
             trade_date, status, param_version, map_version,
             bar_coverage, computable_coverage, limit_coverage_asof, tradable_count
           ) VALUES (?,?,?,?,?,?,?,?)""",
        ("2024-01-10", "ok", "p05-v1", "p05-v1", 1.0, 1.0, 1.0, 1),
    )
    conn.commit()
    path = tmp_path / "heartbeat.json"
    _write_nested(path, status="skip", date="2024-01-10", asof="2024-01-10",
                  days=["2024-01-10"], statuses=["skip"])
    ok, why = live_publish_allowed(conn, "2024-01-10", heartbeat_path=str(path))
    assert not ok and why == "skip"
    conn.close()
```

Keep existing flat-fixture regression tests.

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement view + wire three readers**

```python
def _heartbeat_job_view(data: dict) -> dict:
    job = data.get("daily_run")
    return job if isinstance(job, dict) else data
```

- `trade_date_from_heartbeat`: read `status`/`days`/`asof`/`date` from view.  
- `live_publish_allowed` skip: view `status==skip` and `(date or asof) == trade_date`.  
- `heartbeat_asof_dates`: after resolving asof via `trade_date_from_heartbeat`, load JSON again **or** share helper to get view `days` list (not top-level).

- [ ] **Step 4: PASS (nested + flat shadow)**

```bash
python3 -m pytest tests/test_issue_heartbeat_gate.py tests/test_live_shadow_gate.py -q
```

- [ ] **Step 5: Commit**

```bash
git add scripts/issues/update_l1_issues.py scripts/eval/live_shadow_step.py \
  tests/test_issue_heartbeat_gate.py
git commit -m "$(cat <<'EOF'
fix(heartbeat): read nested daily_run job view for Issues and shadow

EOF
)"
```

---

### Task 4: Workflow `only_date` shadow pin

**Files:**
- Modify: `.github/workflows/daily-trend.yml`
- Test: `tests/test_p2_workflow_order.py` (preferred) or `tests/test_workflow_only_date_shadow.py`

**Interfaces:**
- `only_date` + `date` → **only** `live_shadow_step.py --asof "$DATE"`
- else → `--from-heartbeat`

- [ ] **Step 1: Failing static test — parse the live_shadow run block**

```python
def test_workflow_only_date_shadow_uses_asof_not_heartbeat():
    from pathlib import Path
    import re
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
```

(Adjust quote escaping to match the YAML you write.)

- [ ] **Step 2: Implement YAML**

```yaml
      - name: live_shadow
        if: ${{ success() && steps.sync.outputs.sync_complete == 'true' && steps.sync.outputs.run_deferred != 'true' }}
        run: |
          DATE="${{ github.event.inputs.date }}"
          ONLY="${{ github.event.inputs.only_date }}"
          if [ "$ONLY" = "true" ] && [ -n "$DATE" ]; then
            python scripts/eval/live_shadow_step.py --asof "$DATE"
          else
            python scripts/eval/live_shadow_step.py --from-heartbeat
          fi
```

- [ ] **Step 3: PASS + commit**

```bash
git add .github/workflows/daily-trend.yml tests/test_p2_workflow_order.py
git commit -m "$(cat <<'EOF'
fix(ci): pin live_shadow --asof on only_date runs

EOF
)"
```

---

### Task 5: Done-when docs

**Files:** `todo.md`, Spec A status → 已落地, README one-liner if useful

- [ ] Mark Spec A **done** in 切片路线; §1.1–1.2 point to landed plan
- [ ] Spec status → `已落地；plan 见 2026-10-07-ops-daily-run-hemostasis.md`
- [ ] Run:

```bash
python3 -m pytest tests/test_p0_core.py tests/test_daily_run_metrics_wire.py \
  tests/test_p05_data_wiring.py tests/test_issue_heartbeat_gate.py \
  tests/test_live_shadow_gate.py tests/test_p2_workflow_order.py -q
python3 -m pytest tests/ -q
```

- [ ] Commit docs status bumps only (authority docs already in Task 0)

```bash
git add todo.md docs/superpowers/specs/2026-10-07-ops-daily-run-hemostasis-design.md README.md
git commit -m "$(cat <<'EOF'
docs: mark Spec A ops hemostasis ready for ship

EOF
)"
```

---

## Out of this plan

- Spec B–E; historical limits; board_calc; auto re-fetch limits after soft ok
- Changing EM retry beyond existing soft-fail
- Committing production `trend.db` / holiday re-run (Actions follow-up)

## Done when

1. Soft ok unit + wire: `status=ok`, warn set, `ok_predicate_version=v1.2`, `last_ok` advances  
2. Queue/resume uses hard-partial for gaps; soft-limit does not create resume holes  
3. Nested heartbeat: date + full `days` + skip  
4. Workflow only_date shadow uses `--asof` only (cron keeps `--from-heartbeat`)  
5. Offline pytest green; docs/todo A done; B next  

---

## Plan self-review

| Spec § | Task |
|--------|------|
| §3.2 soft gate / v1.2 | T1 |
| §3.2.1 warn / §3.2.2 last_ok | T2 |
| §3.6 test flips | T1–T2 |
| §4 heartbeat view | T3 |
| §5 only_date shadow | T4 |
| §7 acceptance | T0–T5 |
| market-data / YAML authority on git | T0 |
| §2 coverage=0 unchanged | Global Constraints |

### Plan CR follow-up

| Finding | Verdict | Action |
|---------|---------|--------|
| `test_queue_stops_*` 必依赖低 limit→partial | **真** | Task 2 Step 4 强制改写 |
| 未删除 `test_ok_asof_requires_limits` | **真** | Task 1：Delete entirely |
| wire 测缺脚手架 | **真** | Task 2：沿用旧 `_patch_run` |
| Task 4 静态断言过宽 | **真** | 解析 then 分支 |
| `heartbeat_asof_dates` 测落点飘 | **真** | 钉在 gate 测 |
| market-data/YAML 未强制首 commit | **真** | Task 0 |
| `test_process_day_uses_real_coverage` 清 limit→partial | **真 blocker** | Task 2 翻 p05；grep 其它 limit-only→partial |
| Task 3 夹具/PASS 不全 | **真** | 完整 `_write_nested`；PASS + `test_live_shadow_gate` |
| soft last_ok 具名用例可选 | **真** | 强制 `test_asof_soft_limit_advances_last_ok` |
| skip 须 `date\|asof` | **真** | Task 3 Interfaces + Step 3 |
| T1∥T3 同文件冲突 | **假** | 无冲突 |
| Spec 与 plan 口径矛盾 | **假** | — |
