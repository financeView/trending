# Spec F：workflow 拆 sync + metrics 两 job — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `daily-trend.yml` into `sync` + `metrics` jobs; remove `run_deferred` gate and production `--time-budget-min` 200/300 truncation so metrics always runs after a complete sync on its own 6h runner.

**Architecture:** Same workflow, two jobs. `sync` owns tests → taxonomy → `sync_bars_sample` (incl. Spec E passes) and writes `sync_complete`. `metrics` `needs: sync` and runs only when `sync_complete=true`, restoring `data/cache` via `bars-${{ github.run_id }}`. No cross-job `run_deferred` skip.

**Tech Stack:** GitHub Actions; `actions/cache@v4`; existing `scripts/sync_bars_sample.py` / `daily_run.py`; pytest static workflow tests.

**Spec:** [`docs/superpowers/specs/2026-10-08-workflow-split-jobs-design.md`](../specs/2026-10-08-workflow-split-jobs-design.md)

## Global Constraints

- Do not change Spec E pass algorithms or daily_run business logic.
- Keep `concurrency.group: daily-trend` and `cancel-in-progress: false`.
- Production cron/only_date: no `--time-budget-min` (or `0`).
- Workflow must not reference `run_deferred` in any `if:`.
- Single `trend.db`+heartbeat commit remains in metrics job only.
- metrics must checkout default-branch **tip** (not bare `GITHUB_SHA`) after sync may have pushed taxonomy/heartbeat/first_seen.
- metrics bars restore: exact `bars-${{ github.run_id }}` hit required; no stale `restore-keys` fallback on metrics.
- Exclude committing `data/cache/trade_dates.json` / local heartbeat noise from agent commits unless the metrics job itself commits them on Actions.

---

## File map

| File | Role |
|------|------|
| `.github/workflows/daily-trend.yml` | Two jobs; outputs; cache; gates |
| `scripts/sync_bars_sample.py` | `write_sync_complete`: drop deferred gate/output; optional incomplete warning helper for CI |
| `tests/test_p2_workflow_order.py` | Assert two-job structure and new gates |
| `tests/test_sync_budget.py` (or new `test_sync_complete_output.py`) | Assert no deferred gating from elapsed |
| `README.md` | Document two-job + incomplete semantics |
| `docs/superpowers/specs/2026-10-05-sw-yaml-universe-design.md` | Mark run_deferred superseded |
| Spec E / Spec D touch sentences | Clarify sync **job** vs metrics job |
| `todo.md` | Point P3 run_deferred at Spec F |

---

### Task 1: `write_sync_complete` — remove deferred gate

**Files:**
- Modify: `scripts/sync_bars_sample.py`
- Modify: `tests/test_sync_budget.py` (or add focused test file if none covers deferred)

- [ ] **Step 1: Read current tests** for `write_sync_complete` / `run_deferred` / time budget

```bash
.venv/bin/pytest tests/test_sync_budget.py tests/test_sync_from_universe.py -q --collect-only
rg -n "run_deferred|write_sync_complete|time-budget" tests scripts/sync_bars_sample.py
```

- [ ] **Step 2: Update / replace deferred assertions**

**Must change** existing `tests/test_sync_budget.py::test_github_output_sync_complete` — today it **requires** `run_deferred=true` at `elapsed_min=201` (will FAIL the suite if left unchanged).

Rewrite to:

```python
def test_github_output_sync_complete(tmp_path, monkeypatch):
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    write_sync_complete(True)
    write_sync_complete(False)
    write_sync_complete(True, elapsed_min=201.0)
    text = out.read_text(encoding="utf-8")
    assert "sync_complete=true" in text
    assert "sync_complete=false" in text
    assert "run_deferred=true" not in text  # Spec F: no deferred gate
```

Optional extra: `assert text.count("sync_complete=true") >= 2`.

- [ ] **Step 3: Run test — expect FAIL** on old code

```bash
.venv/bin/pytest tests/test_sync_budget.py::test_github_output_sync_complete -q
```

- [ ] **Step 4: Implement** — in `write_sync_complete`, remove deferred computation; **stop writing** `run_deferred` (preferred). Keep stdout log with `elapsed_min`.

- [ ] **Step 5: Run tests — expect PASS**

```bash
.venv/bin/pytest tests/test_sync_budget.py -q
```

- [ ] **Step 6: Commit**

```bash
git add scripts/sync_bars_sample.py tests/test_sync_budget.py
git commit -m "$(cat <<'EOF'
fix(sync): drop run_deferred gate from write_sync_complete

EOF
)"
```

---

### Task 2: Reshape `daily-trend.yml` into two jobs

**Files:**
- Modify: `.github/workflows/daily-trend.yml`
- Modify: `tests/test_p2_workflow_order.py`

- [ ] **Step 1: Rewrite failing workflow tests** first (TDD on static file)

Replace `_GATE` / single-job assumptions with concrete asserts:

```python
def _metrics_block(text: str) -> str:
    m = re.search(r"^  metrics:\n(.*?)(?=^  [a-z]|^\Z)", text, re.M | re.S)
    assert m, "metrics job missing"
    return m.group(1)

def test_workflow_has_sync_and_metrics_jobs():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    assert re.search(r"^  sync:\s*$", text, re.M)
    assert re.search(r"^  metrics:\s*$", text, re.M)
    assert "needs: sync" in text or "needs: [sync]" in text
    assert "run_deferred" not in text
    assert "needs.sync.outputs.sync_complete" in text
    assert text.count("bars-${{ github.run_id }}") >= 2
    assert text.count("timeout-minutes: 360") >= 2
    met = _metrics_block(text)
    assert "ref:" in met or "repository.default_branch" in met  # tip checkout, not bare trigger SHA
    assert "cache-hit" in met  # exact-key gate
    assert "BARS_SOURCE" in text

def test_metrics_ordered_daily_shadow_commit_issues():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    met = _metrics_block(text)
    daily = met.index("python scripts/daily_run.py")
    shadow = met.index("live_shadow_step.py")
    commit = met.index("git add data/trend.db data/heartbeat.json")
    issues = met.index("update_l1_issues.py")
    assert daily < shadow < commit < issues
    assert met.count("git commit -m") == 1
```

Keep: unit → taxonomy → sync order **inside sync job**; only_date shadow `--asof`; Issues `continue-on-error`.

- [ ] **Step 2: Run tests — expect FAIL**

```bash
.venv/bin/pytest tests/test_p2_workflow_order.py -q
```

- [ ] **Step 3: Implement yml skeleton**

Required shape (fill inputs/scripts from current file; do not invent new CLI flags):

```yaml
jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    outputs:
      sync_complete: ${{ steps.sync.outputs.sync_complete }}
      taxonomy_head_sha: ${{ steps.taxonomy.outputs.taxonomy_head_sha }}
      taxonomy_fetch: ${{ steps.taxonomy.outputs.taxonomy_fetch }}
    steps:
      # checkout, setup-python, pip, cache restore key bars-${{ github.run_id }}
      # Unit tests
      # Refresh taxonomy YAML (id: taxonomy)
      # Sync mapped-universe bars (id: sync):
      #   - NO BUDGET=200/300; omit --time-budget-min (or pass 0)
      #   - keep --end / --asof / LIMIT_ARGS / only_date logic
      #   - on sync_complete=false: echo "::warning::sync_incomplete — metrics job will be skipped"
      # cache saves at job end automatically

  metrics:
    needs: sync
    if: ${{ needs.sync.outputs.sync_complete == 'true' }}
    runs-on: ubuntu-latest
    timeout-minutes: 360
    env:
      BARS_SOURCE: sina
      PYTHONUNBUFFERED: "1"
    steps:
      # checkout@v4 with ref: main  (or github.event.repository.default_branch)
      #   REQUIRED — default checkout of GITHUB_SHA misses taxonomy/heartbeat pushes from sync job
      # setup-python, pip
      # Restore bars cache id: bars-cache
      #   key: bars-${{ github.run_id }}
      #   DO NOT set restore-keys on metrics (avoid silent stale bars)
      # Fail if steps.bars-cache.outputs.cache-hit != 'true'
      # daily_run (env TAXONOMY_* from needs.sync.outputs); step timeout-minutes: 120 OK
      # live_shadow
      # Commit trend.db + heartbeat (once); pull --rebase before push as today
      # Update L1 / Radar Issues (skip_issue_update honored)
```

Pin:

- Remove sync step `timeout-minutes: 330`.
- Remove all `run_deferred` from `if:`.
- `concurrency` / `permissions` / `on:` unchanged.
- metrics **git tip checkout** + **exact cache-hit gate** (Spec §4.3).

- [ ] **Step 4: Incomplete warning** — after sync script, if output false, emit `::warning::` (bash read `steps.sync.outputs.sync_complete` or parse log). Prefer:

```bash
if [ "${{ steps.sync.outputs.sync_complete }}" != "true" ]; then
  echo "::warning::sync_incomplete — metrics job will be skipped"
fi
```

(as a trailing step in sync job, or inline after sync step)

- [ ] **Step 5: Run workflow static tests — PASS**

```bash
.venv/bin/pytest tests/test_p2_workflow_order.py -q
```

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/daily-trend.yml tests/test_p2_workflow_order.py
git commit -m "$(cat <<'EOF'
ci: split daily-trend into sync and metrics jobs

EOF
)"
```

---

### Task 3: Docs + todo touchpoints

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-05-sw-yaml-universe-design.md` (run_deferred paragraph)
- Modify: Spec E design one clarifying sentence (sync **job** vs metrics)
- Modify: Spec D design if it hard-requires 200/300 + deferred (point to Spec F)
- Modify: `todo.md` P3 `run_deferred` row → Spec F / 进行中 or 完成（实现后标完成）
- Modify: Spec F header status → 已落地（仅在全部任务完成后）

- [ ] **Step 1: README** — replace deferred sentence with two-job description + incomplete warning semantics

- [ ] **Step 2: Cross-specs** — mark superseded deferred/budget lines; link Spec F

- [ ] **Step 3: Commit**

```bash
git add README.md docs/superpowers/specs/todo.md 2>/dev/null
git add README.md docs/superpowers/specs/2026-10-05-sw-yaml-universe-design.md \
  docs/superpowers/specs/2026-10-08-spec-e-fill-hard-freeze-design.md \
  docs/superpowers/specs/2026-10-08-universe-expansion-design.md \
  docs/superpowers/specs/2026-10-08-workflow-split-jobs-design.md \
  todo.md
git commit -m "$(cat <<'EOF'
docs: Spec F two-job workflow; retire run_deferred narrative

EOF
)"
```

---

### Task 4: Smoke verification

- [ ] **Step 1: Full related pytest**

```bash
.venv/bin/pytest tests/test_p2_workflow_order.py tests/test_sync_budget.py tests/test_sync_spec_e_passes.py tests/test_sync_from_universe.py -q
```

- [ ] **Step 2: Manual Actions** (after push) — `workflow_dispatch` with `date` + `only_date` on a recent day; confirm metrics job **runs** even if sync wall time >200m (as long as complete). Confirm cache restore in metrics logs.

- [ ] **Step 3: Mark Spec F status 已落地** + todo row; commit if not done in Task 3

---

## Done-when checklist

- [ ] Two jobs; metrics needs sync; no `run_deferred` in yml  
- [ ] Production sync omits time-budget truncation  
- [ ] `write_sync_complete` does not emit deferred=true gate；`test_github_output_sync_complete` updated  
- [ ] metrics checkout default-branch tip；exact `cache-hit` fail gate  
- [ ] Static tests green（含双 cache key、metrics 步序）  
- [ ] Docs/README/todo updated  
- [ ] (Manual) long complete sync still starts metrics job；metrics log shows cache-hit true 

---

## Out of scope reminders

- Radar T\* / stock `name_zh`  
- Raising hosted 6h cap  
- Splitting concurrency groups  
