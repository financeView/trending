# P0 Daily Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a runnable P0 loop: trade-calendar gate → bars schema/sync **skeleton** → `trend.db` `run_meta` with §7.2 `ok` predicate → GitHub Actions cron 北京 19:00 + resume by contiguous `last_ok`（§7.3 不越过失败日）.

**Architecture:** Mirror `economy-strategy` (http limiter, sina calendar, Actions `data/cache` bars) but dual-store qfq/raw per market-data-contract; formal facts in committed `data/trend.db`. Metrics FSM/solar full engine is P0.5+; P0 includes calendar, bars schema/sync skeleton, coverage/`ok`, `daily_run`, gold fixture path.

**P0 bars wiring（钉死）:** `daily_run` **默认不**全宇宙 sync；用 stub coverage 写 `run_meta` 即可验收门禁/续跑。`sync_symbol_bars` 保留为可选手动/抽样（`scripts/sync_bars_sample.py`）。真实覆盖率统计进 P0.5 前再接线。

**重算策略：** ops §3.3 **Strategy A** — UPSERT `run_meta`（及日后 `daily_*`）；`signal_event` / `paper_fill` 仍 append-only（P0.5+）。

**Tech Stack:** Python 3.11, akshare, pandas, sqlite3, pytest, GitHub Actions.

## Global Constraints

- Specs: taxonomy / metrics / ops / backtest / [`2026-10-01-market-data-contract-design.md`](../specs/2026-10-01-market-data-contract-design.md)
- `ts_code` = Tushare `XXXXXX.SH|SZ`
- Cron: UTC `0 11 * * 1-5` (北京 19:00)
- Missing historical `limit_*` → `data_gap` at fill time; only **session asof** requires `limit_coverage_asof ≥ 0.80` for `ok`
- `float_mv`: store; null → `w=1.0` then normalize; never paint today’s spot onto past dates
- Bars: never mix sina/em on one symbol (`BARS_SOURCE`)
- **续跑：** 队列遇首个 `status≠ok` **立即停**；`last_ok` = 自库内最早日起的**连续 ok 前缀末尾**（不得用「任意最大 ok 日」越过中间的 partial/fail）

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/common/http.py` | RateLimiter + call_with_retry |
| `scripts/common/calendar.py` | trade calendar + prev/next_trade_date |
| `scripts/common/ts_code.py` | vendor ↔ Tushare code |
| `scripts/common/db.py` | trend.db schema, upsert, heartbeat, contiguous last_ok |
| `scripts/common/bars.py` | bars.db schema + sync skeleton |
| `scripts/common/coverage.py` | ok predicate §7.2 |
| `scripts/daily_run.py` | CLI: gate, resume queue, **stop on non-ok**, stub coverage → run_meta |
| `scripts/sync_bars_sample.py` | optional 抽样 sync（非 daily_run 默认路径） |
| `config/metrics/a_share_daily.yaml` | metrics params |
| `config/eval/costs.yaml` | costs + limit_rule |
| `fixtures/temp_raw_gold.csv` | T_raw gold（≥ few rows） |
| `scripts/metrics/temp_raw.py` | 金标布尔树 stub（全树属 P0.5） |
| `tests/` | offline unit tests |
| `.github/workflows/daily-trend.yml` | cron + `workflow_dispatch` + cache |

## Tasks

### Task 1: Scaffold + calendar + http + ts_code

- [x] Create dirs, `requirements.txt`, `.gitignore`, configs
- [x] Port `http.py`, extend `calendar.py` with `prev_trade_date`/`next_trade_date`
- [x] `ts_code.py` convert helpers
- [x] Offline tests with cached `trade_dates.json` fixture
- [x] Commit（`d23b41a` 等）

### Task 2: trend.db + coverage ok predicate

- [x] `db.py` SCHEMA: `run_meta`（coverage 列）、`daily_stock`（含 `float_mv`）、`signal_event`/`paper_fill` stub
- [x] `daily_stock` 列对齐 ops：`close_qfq`（替换 `close`）、可空 `hard_frozen`（P0 不计算，仅占位）
- [x] `coverage.py`: `evaluate_ok(D, session_asof, metrics)` per §7.2
- [x] Unit tests: history day missing limits can ok; asof low limit → not ok
- [x] Commit（初版）；列名修补另 commit

### Task 3: bars.db dual qfq/raw skeleton

- [x] `bars.py` CREATE TABLE per market-data-contract
- [x] `sync_symbol_bars(ts_code, end_date)` sina raw+qfq（optional network）
- [x] Unit test: schema create + upsert roundtrip without network
- [x] Commit

### Task 4: daily_run + Actions + 续跑硬闸

- [x] `daily_run.py --date/--force-trade-day`: skip non-trade day; resume queue; write `run_meta`
- [x] **停队列：** `process_day` 返回 `≠ok` 则不再处理后续 D（§7.3）
- [x] **`last_ok` / resume：** 连续 ok 前缀；首个 partial/fail 日为下次起点（禁止最大 ok 日越过缺口）
- [x] 单测：gap 后最大 ok 不越过；resume 从首个非 ok 起
- [x] `.github/workflows/daily-trend.yml` cron `0 11 * * 1-5` + `workflow_dispatch`（`date` / `force_trade_day`）, cache `data/cache`
- [x] Smoke: offline `--date` + `--force-trade-day`
- [x] Commit（初版）；续跑硬闸另 commit

### Task 5: Metrics gold path (minimal)

- [x] `fixtures/temp_raw_gold.csv` + loader / `decide_t_raw` 单测
- [x] `scripts/metrics/temp_raw.py`（布尔列 stub；完整 §5.1 树 → P0.5）
- [x] Commit

## Out of P0 (next plans / **P0.5+**)

- Full T_raw decision tree + hysteresis + FSM suite（ops **P0.5**：计算并落库 `daily_*` + `signal_event`；含 metrics §6.0 / `hard_frozen` 计算）
- 真实 bars 覆盖率统计接线进 `daily_run`；BaoStock ST/suspend + EM f51/f52 daily limits
- L1 Issues（P1）, paper_book / live_shadow（P2；L 须 `run_meta=ok`）
- Taxonomy YAML full SW map load

## Done when（对齐 ops §9 P0）

1. `pytest tests/ -q` 离线绿（日历 / ok 谓词 / 金标 / **续跑不停越过**）  
2. `daily_run` 非交易日 skip exit 0；假日不写空业务 commit（heartbeat-only 变更可接受或 workflow 跳过无 staged 变更）  
3. Coverage 单测编码 asof vs history limit 规则  
4. Workflow：cron 北京 19:00 + bars cache；`workflow_dispatch` 可指定历史日重算 `run_meta`  
5. 本地 `--date <交易日>` 跑通，`run_meta` 有覆盖率字段；**不要求**完整 `daily_stock` T/FSM  
