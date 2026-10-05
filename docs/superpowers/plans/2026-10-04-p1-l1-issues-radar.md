# P1 L1 Issues + Radar + Actions Real Coverage

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship ops §5 human interface (14 L1 Issues + Radar digest consuming persisted `daily_*` / `signal_event`) and remove Actions `--stub-coverage` by syncing the classification-universe stub into the workflow before `daily_run`.

**Architecture:** Pure digest renderers read `trend.db` only (no bars replay). A thin CLI upserts GitHub Issues by title/label (create-or-replace body). Actions adds a network sync of `universe_stub.yaml` members (OHLC + flags + asof limits) then runs `daily_run` with **real** coverage; Issue update runs after a successful `run_meta` write (skip on non-trading-day / when `status=fail`).

**Tech Stack:** Python 3.11, sqlite3, PyYAML, `gh` API / `urllib` + `GITHUB_TOKEN`, pytest, GitHub Actions.

## Global Constraints

- Specs: ops [`2026-09-30-ops-action-and-eval-design.md`](../specs/2026-09-30-ops-action-and-eval-design.md) §5 / §8–§9 P1 · taxonomy [`2026-09-28-industry-taxonomy-design.md`](../specs/2026-09-28-industry-taxonomy-design.md) §3.3 (14 `l1_id`) · market-data §7.2 ok predicate
- Issue titles: `[L1] {中文名} ({l1_id})`；Radar: `[Radar] A股战场`
- Body = **full overwrite** for `as_of` / trade_date；header pins `as_of`, `param_version`, `map_version`, run URL
- Discovery: label `l1-dashboard` (L1) / `radar-dashboard` (Radar) + exact title match; else create
- Non-trading-day: do **not** update Issues (same as ops §5.3)
- Dangerous / exit-tag signals stay off Issue main lists unless flag later
- Taxonomy MVP may still be stub map (few stocks → few L1s with rows); **still create/update all 14 L1 Issues** (empty sections OK)
- **Not in P1:** same-engine L2/L1 (§10 C5), full SW2021 member YAML, paper_book / live_shadow, Spearman gates
- Coverage: Actions syncs **stub universe only** (not full A-share); removing stub means real coverage over that U — document honestly

## File map

| Path | Responsibility |
|------|----------------|
| `config/taxonomy/l1_buckets.yaml` | Canonical 14 `l1_id` + 中文名 + sort（对齐 taxonomy §3.3） |
| `scripts/common/taxonomy_meta.py` | Load L1 bucket meta (ids, names, sort) |
| `scripts/issues/digest.py` | Pure: query trend.db → markdown for one L1 / Radar |
| `scripts/issues/update_l1_issues.py` | CLI: render + dry-run files / live GitHub upsert |
| `scripts/sync_bars_sample.py` | Extend: `--from-universe` reads universe YAML members |
| `.github/workflows/daily-trend.yml` | Sync stub U → real coverage daily_run → optional Issue update |
| `tests/test_l1_digest.py` | Offline synthetic daily_* → markdown assertions |
| `tests/test_taxonomy_meta.py` | 14 ids / stable titles |
| `README.md` | P1 usage + Actions real-coverage note |

## Parallelism

```text
Task 1 (taxonomy meta) ─┬─► Task 2 (digest pure) ─► Task 3 (CLI dry-run) ─► Task 4 (gh upsert)
                        │
                        └─► Task 5 (sync --from-universe) ─► Task 6 (Actions wire) ─► Task 7 (docs + Done-when)
```

Tasks 2 and 5 can run in parallel after Task 1. Task 4 needs a token in Actions; unit tests stay dry-run only.

---

### Task 1: Canonical 14 L1 bucket meta

**Files:**
- Modify: `config/taxonomy/l1_buckets.yaml`
- Create: `scripts/common/taxonomy_meta.py`
- Test: `tests/test_taxonomy_meta.py`

**Interfaces:**
- Produces: `load_l1_buckets(path=None) -> list[L1Bucket]` where `L1Bucket` has `l1_id`, `name_zh`, `sort`
- Produces: `l1_issue_title(bucket) -> str` = `[L1] {name_zh} ({l1_id})`
- Produces: `RADAR_TITLE = "[Radar] A股战场"`

- [x] **Step 1:** Rewrite `l1_buckets.yaml` to the 14 rows from taxonomy §3.3 (replace stub `l1_tmt` / `l1_consumer` / `l1_cycle`)
- [x] **Step 2:** Failing test: `len(load_l1_buckets()) == 14` and titles unique
- [x] **Step 3:** Implement loader; pytest green
- [ ] **Step 4:** Commit

### Task 2: Pure digest renderer (offline)

**Files:**
- Create: `scripts/issues/digest.py`
- Create: `scripts/issues/__init__.py`
- Test: `tests/test_l1_digest.py`

**Interfaces:**
- Consumes: `trend.db` schema (`daily_stock`, `daily_l2`, `daily_l1`, `signal_event`, `run_meta`)
- Produces:
  - `render_l1_issue(conn, trade_date, l1_id, *, name_zh, top_n=20) -> str`
  - `render_radar_issue(conn, trade_date, buckets, *, top_n=20) -> str`
- Sort L2: `rank(T)` desc then `S_temp` desc；个股温转热 / 右侧：`amount` / `RS` as available
- Active events only: `superseded_by IS NULL`
- Empty L1 (no members in stub map): still emit skeleton with meta + empty tables

- [x] **Step 1:** Failing tests with in-memory/tmp trend.db seeded rows for `l1_finance`
- [x] **Step 2:** Implement queries + markdown skeleton matching ops §5.2
- [x] **Step 3:** Radar: right-side ratio, warm-to-hot counts, L1 table sorted by right-side share / warm-to-hot
- [x] **Step 4:** pytest green; Commit

### Task 3: CLI dry-run (`update_l1_issues.py`)

**Files:**
- Create: `scripts/issues/update_l1_issues.py`
- Test: `tests/test_update_l1_issues_cli.py`

**Interfaces:**
- CLI: `--date YYYY-MM-DD --dry-run --out-dir DIR [--db PATH]`
- Writes `DIR/{l1_id}.md` ×14 + `DIR/radar.md`
- Exit 0 when `run_meta` exists for date (any status); warn if missing rows
- Does **not** call GitHub in dry-run

- [x] **Step 1:** Failing CLI test (tmp_path out-dir)
- [x] **Step 2:** Implement; wire taxonomy_meta + digest
- [ ] **Step 3:** Commit

### Task 4: GitHub Issue upsert

**Files:**
- Modify: `scripts/issues/update_l1_issues.py`
- Test: `tests/test_github_issue_upsert.py` (mock HTTP / no network)

**Interfaces:**
- `upsert_issue(*, title, body, labels, token, repo) -> issue_number`
- Live mode: `--live` requires `GITHUB_TOKEN` + `GITHUB_REPOSITORY`
- Find by label + exact title; PATCH body or POST create
- Skip live update when env `SKIP_ISSUE_UPDATE=1`

- [x] **Step 1:** Mock tests for create vs update paths
- [x] **Step 2:** Implement minimal REST (urllib); no new heavy deps unless already present
- [ ] **Step 3:** Commit

### Task 5: Sync universe stub helper

**Files:**
- Modify: `scripts/sync_bars_sample.py`
- Test: `tests/test_sync_from_universe.py` (arg parse / member list only; network optional skip)

**Interfaces:**
- `--from-universe PATH` → codes = YAML `members` (ignore quarantine)
- Keep existing `--codes` / `--with-limits`

- [x] **Step 1:** Test member extraction from YAML
- [x] **Step 2:** Implement flag; Commit

### Task 6: Actions — real coverage + Issue hook

**Files:**
- Modify: `.github/workflows/daily-trend.yml`
- Modify: `README.md` (Actions note)

**Steps in workflow (after unit tests):**
1. `python scripts/sync_bars_sample.py --from-universe config/taxonomy/universe_stub.yaml --with-limits` (end=date or today)
2. `python scripts/daily_run.py …` **without** `--stub-coverage`
3. Commit `trend.db` + heartbeat
4. Best-effort Issue upsert (`continue-on-error`; `--from-heartbeat` on cron, `--date` on dispatch)

**Notes:**
- timeout already 180m; stub U ≈5 names × ~400d is fine
- EM/sina flake → honest `partial`/`fail` (acceptable; do not reintroduce silent stub)
- Optional: `continue-on-error: false` on sync; document re-run via `workflow_dispatch`

- [x] **Step 1:** Patch workflow permissions + steps
- [x] **Step 2:** README: P1 + real coverage over stub U (not full A-share)
- [ ] **Step 3:** Commit

### Task 7: Done-when hardening

- [x] Offline: `pytest tests/ -q` includes taxonomy meta + digest + dry-run CLI + mocked gh
- [ ] Manual checklist (not CI gate): with token, `--live` updates one L1 Issue body containing `as_of` + 温转热 section header
- [x] Plan checkboxes; README Done-when for P1
- [ ] Commit

## Out of P1

- Full SW2021→stock YAML / quarantine production load
- Same-engine basket (§10 C5)
- paper_book / live_shadow / paper_fill consumption
- Full-A sync in Actions
- P3 pages

## Done when（对齐 ops §9 P1）

1. Offline pytest green: 14 bucket meta, L1+Radar markdown from synthetic DB, dry-run CLI, mocked upsert
2. Actions runs sync(stub U) → `daily_run` **without** `--stub-coverage` → commits `trend.db`
3. Live path can update 14 L1 Issues + Radar (body has `as_of` + 温转热表头); empty L1 still gets skeleton
4. Non-trading-day / `daily_run` skip → Issues untouched
5. **不要求** full-A universe, same-engine L2, or qualitative chart QA in CI (ops §9.2 remains human spot-check)
