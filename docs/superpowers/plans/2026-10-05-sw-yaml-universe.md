# SW YAML Universe + Historical --date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace stub-5 / `STUB_*` with the Git SW2021 mapped universe; batch-sync those members; fix `--date` so reruns of a failed day are historical (`D < session_asof`) not fake asof; then actually run 2026-09-30.

**Architecture:** YAML is canonical (`sw_l2_to_l1` + `stock_sw_l2`). `sw_l2_code` = taxonomy §4 six-digit codes only (never 801xxx in production). Universe codes derived (mapped, non-quarantine). `session_asof` is `latest_trade_day()` unless `--asof`. `--date D` is replay start (`--only-date` → `[D]`). `mapped_sync_coverage` gates ok. Sync jobs budget time/count; OHLC vs flags skip separately; incomplete sync never starts `daily_run`.

**Tech Stack:** Python 3.11, PyYAML, sqlite3, GitHub Actions cache, pytest.

## Global Constraints

- Spec: [`2026-10-05-sw-yaml-universe-design.md`](../specs/2026-10-05-sw-yaml-universe-design.md)
- `evaluate_ok`: D < asof no limit gate; D == asof requires limits; **all days** require `mapped_sync_coverage≥0.90`
- Historical `--end` ≠ Shanghai today: skip EM `--with-limits`
- L still skips days without usable open+limits
- Do not commit `data/cache/trade_dates.json` / `data/heartbeat.json` in feat commits
- Out: C5 same-engine, unmapped 全A, board_calc, WF, cron fetch of members YAML

## File map

| Path | Responsibility |
|------|----------------|
| `config/taxonomy/sw_l2_to_l1.yaml` | SW2021 **§4** L2 → 14 L1 |
| `config/taxonomy/stock_sw_l2.yaml` | generated members, §4 codes (check-in) |
| `scripts/taxonomy/fetch_sw_members.py` | one-shot; normalize vendor codes → §4 |
| `scripts/common/universe.py` | derive U / quarantine / map_version |
| `scripts/common/coverage.py` | `mapped_sync_coverage` |
| `scripts/common/db.py` | `run_meta` 新列 |
| `scripts/metrics/aggregate.py` | drop STUB_* |
| `scripts/daily_run.py` | `--date` / `--only-date` / `--asof` |
| `scripts/sync_bars_sample.py` | budget; OHLC/flags skip independently |
| `.github/workflows/daily-trend.yml` | three modes; timeouts 360/330; incomplete gate |
| `tests/test_universe_yaml_map.py` | §4 invariants; no 801xxx as live codes |
| `tests/test_daily_run_date_asof.py` | date ≠ asof; only-date; date-to-asof queue |
| `tests/test_mapped_sync_coverage.py` | 5 synced names cannot ok a large map |
| `tests/test_sync_budget.py` | resume / flags vs last_bar_date |

---

### Task 1: `--date` ≠ session asof

**Files:** `scripts/daily_run.py`; `tests/test_daily_run_date_asof.py`

- [x] Helper `resolve_session(date_arg, only_date, asof_arg, asof_day)`:
  - `asof_arg=""` → `asof_day` from `latest_trade_day()` (not civil today)
  - `date_arg=2026-09-30`, `only_date=True` → queue `[9-30]`, asof=`asof_day`
  - `only_date=False` → queue `[9-30 … asof_day]`
  - `D > asof` → error; `--only-date` without `--date` → error
- [ ] Watch test fail while `session_asof = parse(args.date)`
- [ ] Implement `--asof`, `--only-date`; default asof `latest_trade_day()`
- [ ] Commit

---

### Task 2: `sw_l2_to_l1.yaml` + loaders

**Files:** YAML from taxonomy §4; `scripts/common/universe.py`; `tests/test_universe_yaml_map.py`

- [ ] Every §4 code once; 14 `l1_id`s match `l1_buckets.yaml`; `map_version: sw2021-v1`
- [ ] `load_l2_to_l1()`, `load_stock_sw_l2()` (empty stock file OK here)
- [ ] Reject / quarantine any 801xxx in production load (test: 801780 does not enter U)
- [ ] Commit

---

### Task 3: Fetch + check-in `stock_sw_l2.yaml`

**Files:** `scripts/taxonomy/fetch_sw_members.py`; `config/taxonomy/stock_sw_l2.yaml`

- [ ] Normalize: vendor 6-digit ∈ §4 set, else exact 中文名 match §4, else null. Never write 801xxx. Drop `.BJ` / non-`SH|SZ`
- [ ] Fixture: 801780 → absent from output YAML; a `.BJ` code not in `load_universe_codes()`
- [ ] CI uses checked-in YAML (no network)
- [ ] `load_universe_codes()` is hundreds+ of SH/SZ names
- [ ] Commit YAML. Do not regenerate in Actions.

---

### Task 4: Kill `STUB_*` + mapped_sync gate

**Files:** `aggregate.py`, `universe.py`, `coverage.py`, `db.py`, `daily_run.py`, README, `l1_buckets.yaml` version; tests that imported STUB

- [ ] `taxonomy_for_stock` from YAML
- [ ] Default U from stock map; stub yaml only in `tests/fixtures/`
- [ ] `mapped_size` / `mapped_sync_coverage` on `run_meta`; `ok_predicate_version=v1.1`; test: mapped_size=100, only 5 have bars+flags → **not ok**
- [ ] `codes_from_universe` / digest tests: fixtures may keep 801780 **only** in test YAML, not production `STUB_*`
- [ ] Commit

---

### Task 5: Sync budget + workflow modes

**Files:** `sync_bars_sample.py`; `.github/workflows/daily-trend.yml`; `tests/test_sync_budget.py`

- [ ] `--max-codes` / `--time-budget-min`; skip OHLC iff end **row** exists; skip flags iff `flag_source`; do not skip **seasoned** names with history &lt; 252 trading days through `end` (IPOs may stay short)
- [ ] Write `sync_complete=true|false` to **GITHUB_OUTPUT** (and print); both **exit 0**
- [ ] Job timeout 360, sync step 330, budget ≤300 (≤200 if this job will also daily_run)
- [ ] Production `--from-universe` **removed**; sync `load_universe_codes()` default
- [ ] Inputs `date` + `only_date`. Cron: no date, end=`latest_trade_day()`, limits on. `only_date`: `--end D` + `--date D --only-date`. Catch-up: `--end`=`latest_trade_day()` + `--date D`
- [ ] `if: steps.sync.outputs.sync_complete == 'true'` on daily_run, L, db commit. If sync elapsed >200 min, skip daily_run (`run_deferred`)
- [ ] Commit

---

### Task 6: 2026-09-30 real run

- [ ] Sync mapped universe through 9.30 (seasoned names ~252-session window; not every IPO)
- [ ] `daily_run --date 2026-09-30 --only-date` → `run_meta` ok if mapped_sync≥0.90 and U bar/computable pass
- [ ] README: three Actions modes; `--date` vs `--asof`
- [ ] **不要求** 9.30 L 成交

## Out of this plan

- Same-engine C5, unmapped 全A, board_calc, WF, cron YAML fetch

## Done when

1. Production U is mapped SW YAML (§4 codes), not 5 stubs  
2. `--date D --only-date` uses `session_asof=latest_trade_day()`  
3. Actions: `GITHUB_OUTPUT` incomplete never plants a `partial` hole  
4. 2026-09-30 `run_meta` is a real mapped-universe day (`mapped_sync_coverage` honest)  
