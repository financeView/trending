# P0 Daily Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a runnable P0 loop: trade-calendar gate → free-stack bars sync (qfq+raw schema) → `trend.db` `run_meta` with §7.2 `ok` predicate → GitHub Actions cron 北京 19:00 + resume by `next_trade_date(last_ok)`.

**Architecture:** Mirror `economy-strategy` (http limiter, sina calendar, Actions `data/cache` bars) but dual-store qfq/raw per market-data-contract; formal facts in committed `data/trend.db`. Metrics FSM/solar full engine is P0.5+; P0 includes calendar, bars schema/sync skeleton, coverage/`ok`, `daily_run`, gold fixture path.

**Tech Stack:** Python 3.11, akshare, pandas, sqlite3, pytest, GitHub Actions.

## Global Constraints

- Specs: taxonomy / metrics / ops / backtest / [`2026-10-01-market-data-contract-design.md`](../specs/2026-10-01-market-data-contract-design.md)
- `ts_code` = Tushare `XXXXXX.SH|SZ`
- Cron: UTC `0 11 * * 1-5` (北京 19:00)
- Missing historical `limit_*` → `data_gap` at fill time; only **session asof** requires `limit_coverage_asof ≥ 0.80` for `ok`
- `float_mv`: store; null → `w=1.0` then normalize; never paint today’s spot onto past dates
- Bars: never mix sina/em on one symbol (`BARS_SOURCE`)

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/common/http.py` | RateLimiter + call_with_retry |
| `scripts/common/calendar.py` | trade calendar + prev/next_trade_date |
| `scripts/common/ts_code.py` | vendor ↔ Tushare code |
| `scripts/common/db.py` | trend.db schema, upsert, heartbeat |
| `scripts/common/bars.py` | bars.db schema + sync skeleton |
| `scripts/common/coverage.py` | ok predicate §7.2 |
| `scripts/daily_run.py` | CLI: gate, resume queue, sync stub, run_meta |
| `config/metrics/a_share_daily.yaml` | metrics params |
| `config/eval/costs.yaml` | costs + limit_rule |
| `fixtures/temp_raw_gold.csv` | T_raw gold (≥ few rows) |
| `tests/` | offline unit tests |
| `.github/workflows/daily-trend.yml` | cron + cache |

## Tasks

### Task 1: Scaffold + calendar + http + ts_code

- [x] Create dirs, `requirements.txt`, `.gitignore`, configs
- [x] Port `http.py`, extend `calendar.py` with `prev_trade_date`/`next_trade_date`
- [x] `ts_code.py` convert helpers
- [x] Offline tests with cached `trade_dates.json` fixture
- [ ] Commit

### Task 2: trend.db + coverage ok predicate

- [x] `db.py` SCHEMA: run_meta (coverage cols), daily_stock (+ float_mv), stubs for signal_event/paper_fill
- [x] `coverage.py`: `evaluate_ok(D, session_asof, metrics)` per §7.2
- [x] Unit tests: history day missing limits can ok; asof low limit → not ok
- [ ] Commit

### Task 3: bars.db dual qfq/raw skeleton

- [x] `bars.py` CREATE TABLE per market-data-contract
- [x] `sync_symbol_bars(ts_code, end_date)` sina raw+qfq (optional network)
- [x] Unit test: schema create + upsert roundtrip without network
- [ ] Commit

### Task 4: daily_run + Actions

- [x] `daily_run.py --date/--force-trade-day`: skip non-trade day; resume queue; write run_meta
- [x] `.github/workflows/daily-trend.yml` cron `0 11 * * 1-5`, cache `data/cache`
- [x] Smoke: `python scripts/daily_run.py --date <fixture> --force-trade-day` offline path
- [ ] Commit

### Task 5: Metrics gold path (minimal)

- [x] `fixtures/temp_raw_gold.csv` + loader test (rows present; tree impl can be stub failing until Task 5b)
- [ ] Optional stub `scripts/metrics/temp_raw.py` for 2–3 gold rows
- [ ] Commit

## Out of P0 (next plans / **P0.5+**)

- Full T_raw decision tree + hysteresis + FSM suite（ops **P0.5**：计算并落库 `daily_*` + `signal_event`；含 metrics §6.0 / `hard_frozen`）
- BaoStock ST/suspend + EM f51/f52 daily limits
- L1 Issues（P1）, paper_book / live_shadow（P2；L 须 `run_meta=ok`）
- Taxonomy YAML full SW map load

## Done when

1. `pytest tests/ -q` green offline  
2. `daily_run` skips non-trade day exit 0  
3. Coverage unit tests encode asof vs history limit rule  
4. Workflow file present with 19:00 cron + bars cache  
