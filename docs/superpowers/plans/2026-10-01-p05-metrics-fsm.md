# P0.5 Metrics FSM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the metrics engine end-to-end for P0.5: real OHLC → §5.1/§5.2 `T_raw` + §5.3 hysteresis → §6 right-side FSM (incl. §6.0 events + `hard_frozen` ends R) → §8.2 solar linear → persist `daily_stock` / `daily_l2` / `daily_l1` + `signal_event`; named §6.4 / §8.9 fixtures green in CI; wire **real** coverage stats into `daily_run` (replace `_stub_coverage`).

**Architecture:** Pure metrics functions under `scripts/metrics/` consume per-symbol OHLC (+ ST/suspend flags) and emit temperature / FSM / solar outputs; `daily_run.process_day` orchestrates load → compute → UPSERT `daily_*` + append `signal_event` → evaluate `run_meta` with **real** coverage. Taxonomy for MVP may be a universe subset / stub L1–L2 map (`map_version` still written). Full SW YAML load, L1 Issues, and paper/live_shadow stay out of this plan.

**Dependency (钉死):** Real coverage wiring **depends on parallel data-wiring work** that populates `bars` with ST / suspend / `limit_*` and can compute `bar_coverage` / `computable_coverage` / `limit_coverage_asof` over `members_tradable` (market-data §7.2). Until those stats exist, keep stub only behind an explicit flag; default path must call the real scorer once data-wiring lands. Do **not** invent coverage from empty bars.

**重算策略：** ops §3.3 **Strategy A** — UPSERT `run_meta` / `daily_stock` / `daily_l2` / `daily_l1`；`signal_event` **append-only**（重跑日新行 + 旧行 `superseded_by`；禁止物理删已被引用行）。

**Tech Stack:** Python 3.11, pandas/numpy (features), sqlite3, PyYAML, pytest, GitHub Actions（沿用 P0 workflow）.

## Global Constraints

- Specs: metrics ([`2026-09-29-trend-metrics-engine-design.md`](../specs/2026-09-29-trend-metrics-engine-design.md) §5–§8 / §6.4 / §8.9) · ops ([`2026-09-30-ops-action-and-eval-design.md`](../specs/2026-09-30-ops-action-and-eval-design.md) §4 schema · §8 P0.5 · §9) · market-data ([`2026-10-01-market-data-contract-design.md`](../specs/2026-10-01-market-data-contract-design.md) §6–§7) · P0 plan ([`2026-10-01-p0-daily-pipeline.md`](./2026-10-01-p0-daily-pipeline.md))
- `ts_code` = Tushare `XXXXXX.SH|SZ`；信号价一律 `close_qfq`；`limit_*` 只与 raw 空间比较（本计划不实现成交层）
- `hard_frozen := is_st OR explicit_hard_freeze_flag`；短停牌 / 单日 `T_raw=null` = **软冻**（不清 R）；ST 结束右侧 + `EXIT_RIGHT` (`forced_exit_untradable`)
- 事件枚举仅：`ENTER_RIGHT` | `EXIT_RIGHT` | `WARM_TO_HOT`（metrics §6.0）；进入日**不**另写 `WARM_TO_HOT`
- 节气：进入日强制谷雨；结束日强制立秋且 `stage_score`/`raw`=**null**（禁止用 0）；只前进 peak；不可算不推进；拒绝 `require_solar_term_for_entry`
- `float_mv`：合成权重 `null→1.0` 再归一；历史禁 spot 回刷
- 续跑硬闸不变：队列遇首个 `status≠ok` 立即停；`last_ok` = 连续 ok 前缀末尾
- Params：`config/metrics/a_share_daily.yaml`；变更 → bump `param_version`（离开 `p0-stub`）
- Feature allowlist only（metrics §4.1）；禁止跨标的 rank 进温度树

## File map

| Path | Responsibility |
|------|----------------|
| `config/metrics/a_share_daily.yaml` | 全参数 + knots_g/d/v + `param_version`（P0.5 正式版号） |
| `scripts/metrics/params.py` | 加载 YAML → frozen dataclass |
| `scripts/metrics/features.py` | OHLC → MA/ADX/σ%ile/ret%ile 等 §4.1 |
| `scripts/metrics/temp_raw.py` | §5.1 谓词 + §5.2 决策树（替换 P0 布尔列 stub） |
| `scripts/metrics/hysteresis.py` | §5.3 bootstrap + max_step + pending |
| `scripts/metrics/fsm.py` | §6 右侧状态机 + emit events |
| `scripts/metrics/solar.py` | §8.2 线性 scorer + cut + clamp |
| `scripts/metrics/s_temp.py` | §5.4 `S_temp`（MVP 保留；可从属） |
| `scripts/metrics/aggregate.py` | L2/L1 合成收益 → 同套纯函数（§10；宇宙子集可 stub） |
| `scripts/metrics/pipeline.py` | 单标的 / 单日编排：features→T→FSM→solar |
| `scripts/common/db.py` | 补齐 `daily_l2`/`daily_l1`；`signal_event` supersede helper |
| `scripts/common/coverage.py` | 保持 §7.2 谓词；新增 `compute_coverage_metrics(...)` 接口（实现可薄包装 data-wiring） |
| `scripts/daily_run.py` | `process_day`：算截面 + 落库 + **真实 coverage** → `run_meta` |
| `fixtures/temp_raw_gold.csv` | ≥20 行：§5.1 特征快照 → `T_raw`（升级列名对齐真实谓词） |
| `fixtures/fsm/*.json` | §6.4 命名夹具（每 ID 一文件或一目录约定） |
| `fixtures/solar/*.json` | §8.9 命名夹具 |
| `tests/test_temp_raw_gold.py` | 金标 CI |
| `tests/test_hysteresis.py` | max_step / 退出快路径 / bootstrap |
| `tests/test_fsm_suite.py` | §6.4 全绿 |
| `tests/test_solar_suite.py` | §8.9 全绿 |
| `tests/test_signal_event_persist.py` | UPSERT daily_* + append/supersede |
| `tests/test_daily_run_coverage_wire.py` | stub 替换；mock coverage 进 `run_meta` |

## Tasks

### Task 1: Params + feature layer (OHLC → §4.1)

- [ ] Extend `config/metrics/a_share_daily.yaml`: add `knots_g` / `knots_d` / `knots_v` (metrics §8.2 初值), `slope_scale`/`band`/`adx_s_*`/`s_vol_weight`/`spearman_min` as needed, bump `param_version` to e.g. `p05-v1`
- [ ] Add `scripts/metrics/params.py`: `load_params(path) -> MetricsParams`
- [ ] Add `scripts/metrics/features.py`:
  - Input: sorted trade-date OHLC frame (`close_qfq` required; high/low for ADX/ATR)
  - Output per date (or asof row): `MA_f`, `MA_s`, `slope_f`, `slope_s`, `ADX`, `sign`, `sigma_n`, `sigma_pctile`, `ret_k`, `ret_pctile`, `atr_pct`, computable flag
  - History不足 → features null / `computable=False`（§3.3：温度需 ~252 日）
- [ ] Unit tests with synthetic OHLC (no network): known SMA; ADX smoke; σ%ile ∈[0,1]; short series → not computable
- [ ] Commit

### Task 2: Real `T_raw` decision tree (§5.1 / §5.2)

- [ ] Rewrite `scripts/metrics/temp_raw.py`:
  - Implement boolean predicates exactly as metrics §5.1 (`stack_bull/bear`, `hot_body`, `warm_body`, `cold_body`, `cool_body`, `boil_boost`, `freeze_boost`, `flat_body`)
  - Decision order §5.2: 沸→热→温→冻→寒→凉→平→兜底平
  - Keep `RANK` / `rank()` but align numeric ranks to metrics：`沸=3…冻=-3`（与 P0 七档序一致即可用于 max_step）
  - **API:** `decide_t_raw(preds: Mapping) -> str` 仍可测；另提供 `decide_t_raw_from_features(feats, params) -> str | None`（不可算 → `None`）
- [ ] Upgrade `fixtures/temp_raw_gold.csv` to ≥20 rows using **§5.1 predicate columns** (or feature snapshots that deterministically map to them). Update `tests/test_temp_raw_gold.py` accordingly
- [ ] Remove reliance on P0 stub columns (`above_ma20`, `vol_high`, …) once gold migrates; keep a one-release adapter only if needed for green CI mid-refactor, then delete
- [ ] Commit

### Task 3: Hysteresis (§5.3)

- [ ] Add `scripts/metrics/hysteresis.py`:
  - State: `T_prev`, `pending_target`, `pending_count`
  - Bootstrap §5.3.1: first non-null `T_raw` with no usable `T_prev` → synthetic `T_prev=平`, clear pending, then §5.3.2
  - Daily step §5.3.2: extreme adjacency (热↔沸 / 寒↔冻); exit fast-path when `R=true` and `rank(desired)≤0` (clamp stepped ≥平 toward 0); else clip `max_step`; hysteresis_up/down pending
  - `T_raw=null`：不推进滞回（交 FSM §5.5）
- [ ] Tests (`tests/test_hysteresis.py`): bootstrap 首日 `T_raw=热` 不 snap；`max_step=2` 爬升；退出快路径从沸 ≤1 交易日可到平（默认参）；pending 未满保持 `T_prev`
- [ ] Commit

### Task 4: Right-side FSM (§6 including §6.0)

- [ ] Add `scripts/metrics/fsm.py` implementing metrics §6.3 pseudocode:
  - Inputs: `T`, `hard_frozen`, prior state (`R`, days, `T_last_valid`, `T_prev_valid`, solar peak fields, `P0`, …)
  - Priority: `hard_frozen` ends R first → `EXIT_RIGHT` / `exit_kind=forced_exit_untradable` / 立秋 / scores null；**同日不再温度进入**
  - Soft null: `R=true` + `T=null` + not hard → `T_fsm=T_last_valid`；`R=false` + null → skip transitions
  - Enter: `R=false` + `T_fsm∈{热,沸}` → `ENTER_RIGHT`, days=0, force 谷雨, `tag_warm_to_hot=true`（**不** emit `WARM_TO_HOT`）
  - Persist / reconfirm: trading days +=1；温→热/沸 → `WARM_TO_HOT` only
  - Temperature exit: `T_fsm∈{平,凉,寒,冻}` → `EXIT_RIGHT` / `exit_kind=temperature`
  - Natural-day bump helper for calendar gaps (`fsm_fri_mon`)
- [ ] Event records: structured list `{event, T, detail}` for persistence layer
- [ ] Commit（夹具全量在 Task 6）

### Task 5: Solar linear (§8.2)

- [ ] Add `scripts/metrics/solar.py`:
  - `piecewise_linear_clamp(x, knots)` — 禁止端点外推
  - Enter day: force 谷雨, scores 0, **do not** write `v` into peak
  - Ongoing: `g_raw_eff=max(g_raw,0)`, `d_raw`, `v_raw=σ%ile` → weighted raw → peak = max(prev, raw) → `cut(peak)` via `stage_cuts`
  - Exit day: force 立秋；`stage_score`/`raw`=null（不是 0）
  - Not computable (missing P or σ%ile): keep yesterday solar + peak；do not advance
  - Config gate: reject any `require_solar_term_for_entry` if present (`test_C3_reject_solar_entry_gate`)
- [ ] Wire solar updates from FSM persist path only（进入/结束强制覆盖）
- [ ] Commit（§8.9 夹具在 Task 6）

### Task 6: Named fixtures → CI (§6.4 + §8.9)

- [ ] Create `fixtures/fsm/` JSON (or yaml) for **every** ID in metrics §6.4:

  | ID | Must assert |
  |----|-------------|
  | `fsm_enter_hyst` | 热不足 hysteresis_up 不进；满后进 |
  | `fsm_enter_boil` | 首次档沸可进；`tag_warm_to_hot` |
  | `fsm_no_enter_warm` | 长期温永不进 |
  | `fsm_persist_warm` | 热→温存续；`days_trading`↑ |
  | `fsm_exit_warm_to_flat` | 温→平结束；立秋仅当日 |
  | `fsm_exit_hot_to_flat` | `tag_warm_to_flat` |
  | `fsm_exit_boil_to_cool` | 同上 |
  | `fsm_crash_boil_to_freeze` | 退出快路径；≤1 日到平并结束 |
  | `fsm_reconfirm` | `WARM_TO_HOT`；无 `ENTER_RIGHT`；天数不重置 |
  | `fsm_reentry` | 再进 `ENTER_RIGHT`；天数 0 |
  | `fsm_null_in_R` | soft fill；不误结束 |
  | `fsm_null_not_R` | 不进入 |
  | `fsm_fri_mon` | 周末 natural +2 |
  | `fsm_bootstrap` | 冷启动不 snap 进入 |
  | `fsm_untradable_freeze` | 短 null 不立秋、不清 R |
  | `fsm_st_ends_right` | ST → `EXIT_RIGHT` forced + 立秋 + `R=false` |

- [ ] Create `fixtures/solar/` for **every** ID in metrics §8.9:

  | ID | Must assert |
  |----|-------------|
  | `solar_entry_grain_rain` | 进入日高 σ%ile 仍谷雨；score=0 |
  | `solar_jump_on_spike` | 允许单日跳档 |
  | `solar_drawdown_no_retreat` | 回撤不退档；`g_raw_eff=0` |
  | `solar_early_exit_liqiu` | 早夭立秋 |
  | `solar_exit_day_liqiu` | 结束日 scores **is null** |
  | `solar_clamp_high` | g 分量 clamp 1.0；无 NaN |
  | `solar_halt_no_advance` | 不可算不前进、不立秋 |

- [ ] `tests/test_fsm_suite.py` + `tests/test_solar_suite.py`: parametrize over fixture dir；CI must fail if any ID missing
- [ ] Optional: `scripts/metrics/pipeline.py` single-symbol day driver used by fixtures and daily_run
- [ ] Commit

### Task 7: Persist `daily_*` + `signal_event`

- [ ] Extend `scripts/common/db.py` SCHEMA:
  - `CREATE TABLE IF NOT EXISTS daily_l2` / `daily_l1` per ops §4（`trade_date, code, T, S_temp, RS, right_side, …, members_tradable, members_total`）
  - Ensure `daily_stock` columns cover ops §4（已有则核对 `hard_frozen` / `close_qfq` / `float_mv` / tags / solar）
- [ ] Helpers:
  - `upsert_daily_stock/l2/l1(conn, rows)` — Strategy A
  - `append_signal_events(conn, events)` — insert new ids
  - `supersede_signal_events_for_day(conn, trade_date, ts_code, event, new_id)` — 重跑时把同日同标的同 `event` 且 `superseded_by IS NULL` 的旧行指向新 id
- [ ] `scripts/metrics/aggregate.py`（MVP）:
  - Universe subset OK（fixture list or stub map）；`member_set=tradable`
  - Weight by `float_mv` null→1.0 normalize；synthetic series → same pipeline as stock
  - L1 = member closure once（不嵌套 L2）
- [ ] Tests: roundtrip UPSERT idempotent content；signal append + supersede leaves old row；active filter `superseded_by IS NULL`
- [ ] Commit

### Task 8: Wire real coverage into `daily_run`（协调 data-wiring）

**Depends on:** parallel work that can answer, for trade date `D` and universe `U=members_tradable`:

- `bar_coverage` — fraction with raw+qfq OHLC + `is_suspended`/`is_st`（§7.2）
- `computable_coverage` — fraction meeting metrics history gate（§3.3）
- `limit_coverage_asof` — fraction with both `limit_up`/`limit_down` non-null（asof gate only）
- ST / suspend flags available on bars (or joined table) so `hard_frozen` / tradable set are real

- [ ] Add `scripts/common/coverage.py::compute_coverage_metrics(conn_bars, universe, trade_date, *, min_history) -> CoverageMetrics`（薄封装；具体 SQL/统计可委托 data-wiring 模块，但 **符号与返回类型钉在本仓库**）
- [ ] Modify `scripts/daily_run.py`:
  - Remove default `_stub_coverage()` from happy path
  - `process_day`: load bars for universe → run metrics pipeline for computable names → UPSERT `daily_*` → append/supersede `signal_event` → **compute real coverage** → `evaluate_ok` → UPSERT `run_meta` with `param_version` / `map_version` from config
  - Keep `--stub-coverage` **only** for offline smoke without bars（document in `--help`）；CI offline unit tests may use it；Actions daily path must **not**
- [ ] Tests: mock CoverageMetrics low limit on asof → `partial`；history day without limits still `ok` if bar/computable pass；assert `run_meta` fields match computed metrics（not 1.0 stubs）
- [ ] Coordinate checklist（plan gate, not code）:
  - [ ] Data-wiring exposes ST/`is_st` on asof bars
  - [ ] Data-wiring exposes `limit_*` for asof（EM f51/f52 or equivalent）
  - [ ] Universe builder returns `members_tradable` consistent with metrics §3.2
  - [ ] Only then flip Actions / default CLI off stub
- [ ] Commit

### Task 9: Integration smoke + Done-when hardening

- [ ] Offline integration: tiny fixture bars.db (2–3 symbols, ≥252 synthetic sessions) → `daily_run --date … --force-trade-day` writes `daily_stock` rows with non-null `T` where computable；`signal_event` on enter/exit paths from fixture scenario
- [ ] Confirm `pytest tests/ -q` includes gold + fsm suite + solar suite + persist + coverage wire
- [ ] Document in README or plan note: P0.5 does not ship L1 Issues / paper_book
- [ ] Commit

## Out of P0.5

- L1 Issues / radar digests（ops **P1**）
- `paper_book` / `live_shadow` / `paper_fill` 消费（ops **P2**；L 仍须 `run_meta=ok`）
- Full taxonomy SW2021→L1 YAML load（MVP：universe subset + stub `map_version` OK）
- Relative strength full peer regression / 量价混合 RS v1.1（可用 null/`RS` stub on daily_* if column required；正式 RS 可跟 P1）
- Exit tags §11（`exit_tags_enabled` 保持 false）
- Neural / non-linear solar scorer；solar KPI calibration campaigns beyond fixture suite
- `board_calc_v1` limits；Tushare Pro upgrades

## Done when（对齐 ops §9 P0.5）

1. `pytest tests/ -q` 离线绿：含 `temp_raw` 金标（≥20）、`test_fsm_suite`（§6.4 全 ID）、`test_solar_suite`（§8.9 全 ID）、persist/supersede、coverage 非 stub 路径单测  
2. 可算宇宙写出 `daily_stock` / `daily_l2` / `daily_l1`；同日重跑 UPSERT 行内容稳定  
3. `signal_event` 按 §6.0 落库（`ENTER_RIGHT` / `EXIT_RIGHT` / `WARM_TO_HOT`）；重跑 append + `superseded_by`  
4. `hard_frozen`（ST）结束右侧夹具绿；软冻不立秋夹具绿  
5. `daily_run` 默认使用 **真实** bar/computable/limit coverage 写入 `run_meta`（依赖 data-wiring；stub 仅显式 flag）；asof limit 门禁与历史日规则仍满足 market-data §7.2  
6. **不要求** L1 Issues、paper/live_shadow、完整行业 YAML  
