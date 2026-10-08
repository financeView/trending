# Spec E：成交加厚（board_calc）+ 显式硬冻旗

**日期：** 2026-10-08  
**状态：** 设计中（待审）  
**范围：** todo §2.5 `board_calc_v1` / `limit_up_unfillable` + §2.6 显式硬冻（`hard_freeze_flag` / `hard_frozen`）。  
**后放（禁止混入本 slice）：** 树外 bars 预热；asof 日用 board_calc 补洞或自动重拉 limit；付费限价/停牌表（Tushare `stk_limit` / `suspend_d`）；EM `stock_tfp_em` 写入历史 bars；止盈 tag（§2.7）；改温度决策树 / RS / peer；退市整理并入冻旗（taxonomy 已排）。

交叉：market-data [`2026-10-01-market-data-contract-design.md`](2026-10-01-market-data-contract-design.md) §5 · metrics [`2026-09-29-trend-metrics-engine-design.md`](2026-09-29-trend-metrics-engine-design.md) §5.5 · backtest-eval [`2026-09-30-backtest-eval-design.md`](2026-09-30-backtest-eval-design.md) §4 · 研究 [`.superpowers/sdd/spec-e-hard-freeze-sources.md`](../../../.superpowers/sdd/spec-e-hard-freeze-sources.md) · 待办 [`todo.md`](../../../todo.md) §2.5–2.6 / Spec E

产品对齐：历史样本可成交（显式推算、可审计），asof 日仍只信 vendor；长期停牌结束右侧，短停牌继续软冻。

### 相对既有文档的覆盖（钉死）

| 来源 | 原句要旨 | 本 slice |
|------|----------|---------|
| market-data §5.1 | 缺 vendor `limit_*` → `data_gap` | **asof 日保持**；**历史日** `D < session_asof` 允许 `board_calc_v1` 填洞 |
| market-data §5.2 | `board_calc_v1` 未启用；须 `limit_rule` + `cost_version` | **本 slice 启用**；`limit_source=board_calc_v1`，禁止冒充交易所 |
| market-data bars 预留 | `hard_freeze_flag` 可选 | **建列并写入**；sync 据停牌 streak 置位 |
| metrics §5.5 | MVP `hard_frozen := is_st`；连续 N 日后放 | **`hard_frozen := is_st ∨ hard_freeze_flag`**；N 默认 20，入 yaml + `param_version` bump |
| backtest-eval | `limit_up_unfillable`；MVP 卖侧涨停仍尝试 | YAML **显式 `false`**；语义不变 |
| costs.yaml 现状 | `limit_rule: vendor_fields`，无 `limit_up_unfillable` 键 | → `board_calc_v1` + 显式键；bump `cost_version` |

---

## 1. 问题

- 历史多年无 vendor 涨跌停 → 纸面/影子大量 `data_gap`，样本偏薄；契约已预留 `board_calc_v1` 未接线。  
- asof 日若用推算补洞会掩盖东财/同步失败，半截成交风险上升 → **禁止**。  
- `hard_frozen` 仅 `is_st`；长期停牌持仓不清 `R`，与 metrics §5.5 / 研究结论不符。  
- `limit_up_unfillable` 在 fill 代码有默认，**未**进 `costs.yaml`，版本不可审计。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 架构 | **Approach 1：同 job**——sync flags → `hard_freeze_flag` pass → hist `board_calc` pass → `daily_run` |
| board_calc 范围 | **混合：** 仅 `D < session_asof` 且 `limit_*` 皆空时写入；asof **纯 vendor** |
| 持久化 | board_calc 与冻旗均写 **bars**；metrics / fill **读列**，不在引擎内重算板价 |
| `limit_up_unfillable` | 保持 **false**；YAML 显式写出 |
| 硬冻 N | 默认 **20** 个交易日；配置旋钮，改 N 不改代码 |
| 冻旗形态 | sync 写 `bars.hard_freeze_flag`；metrics 读入 `hard_frozen` |

### 2.1 日更顺序

```text
… → sync bars / BaoStock flags（既有）
     → hard_freeze_flag pass（读 is_suspended streak → 写列）
     → board_calc pass（仅 D < session_asof 且 limit 空 → 写 limit_* + limit_source）
→ daily_run（metrics 读 hard_freeze_flag；fill 读 costs）
```

catch-up / 历史追赶日：`session_asof` = 当日 cron 会话 asof；队列内每个 `D` 相对该 asof 判定是否允许 board_calc。

---

## 3. `board_calc_v1` 与 `limit_source`

### 3.1 何时写

| 条件 | 行为 |
|------|------|
| `D < session_asof` ∧ `limit_up` 与 `limit_down` **皆空** ∧ `preclose_raw` 有限且 >0 | 推算并 UPSERT 到该 bar |
| `D = session_asof` | **禁止** board_calc；缺 vendor → 个股意图日仍 `data_gap` |
| 已有任一非空 `limit_*`（含 `em_f51f52` 等） | **不覆盖** |
| `preclose_raw` 缺失 / 非有限正数 | 跳过；保持空 → `data_gap` |

### 3.2 怎么算

价格空间：**未复权 raw**（与 market-data §5.0 一致）。禁止用 qfq 算板。

板幅（v1，按代码前缀 + `is_st`；mapped U 为 SH/SZ，北交所本 slice 不进宇宙）：

| 条件 | 板幅 pct |
|------|----------|
| `is_st = 1` | 5% |
| 代码 `300*` / `688*` | 20% |
| 其余（主板等） | 10% |

```text
limit_up   = round(preclose_raw * (1 + pct), 2)
limit_down = round(preclose_raw * (1 - pct), 2)
```

夹具钉死边界（含 ST 优先于 300/688 前缀）。

### 3.3 落库与成交配置

- `limit_source = board_calc_v1`（不得写 `em_*` 或空源冒充交易所）。  
- `config/eval/costs.yaml`：
  - `limit_rule: board_calc_v1`
  - `limit_up_unfillable: false`（显式）
  - **bump `cost_version`**（如 `v1` → `v2`）
- `Costs` loader 须解析 `limit_up_unfillable` 并传入 fill；summary 写 `limit_rule` + `cost_version`。  
- 有限价后：fill 用既有路径比较 `open_raw` vs `limit_*`（与 vendor 行同一套）。

### 3.4 不做

asof 自动重拉 limit；付费 `stk_limit`；一字板形态代理当限价；静默改 `limit_rule` 却不 bump `cost_version`。

---

## 4. 显式硬冻

### 4.1 语义

```text
hard_frozen := is_st OR hard_freeze_flag
```

- 短停牌 / 缺 `T` / `1 ≤ streak < N` → **软冻**（`T_fill`，不清 `R`）。  
- `hard_frozen ∧ R` → 既有 `EXIT_RIGHT` / `forced_exit_untradable`（不新开旁路）。  
- ST 继续走 `is_st`；**不**要求同时置 `hard_freeze_flag`。

列名：bars / 契约用 `hard_freeze_flag`；与 metrics 文中 `explicit_hard_freeze_flag` **同义**（实现读 bars 列即可）。

### 4.2 置位规则（sync 写 bars）

| 规则 | 约定 |
|------|------|
| 计数轴 | **交易日**；仅 `is_suspended=1` 且 `flag_source` 已设 |
| 窗口 | 以当日 `D` 为终点的连续停牌 streak |
| 阈值 | `streak ≥ N` → `hard_freeze_flag=1`，否则 `0`（含重算覆盖） |
| **N** | `hard_freeze_min_suspend_days`，默认 **20**（`config/metrics/a_share_daily.yaml`） |
| 清旗 | 首个 `is_suspended=0` 的交易日 → streak 归零、`flag=0` |
| 不计 | 日历空洞、OHLC 空占位、无 bar、无 `flag_source`、盘中停牌推断 |

依赖：既有 BaoStock `tradestatus` → `is_suspended`（停牌日有行，见研究笔记）。

### 4.3 metrics

- `replay_from_ohlc` / 截面组装：`hard_frozen = bool(is_st) or bool(hard_freeze_flag)`。  
- **bump `param_version`**（如 `p05-v2` → `p05-v3`）：N 改变 EXIT 时点，须可追溯。  
- 修订 metrics §5.5：「连续 N 日」由本 slice 落地；默认 N=20。

### 4.4 不做

EM tfp 写入历史；退市/暂停上市 OR 进旗（v1.1）；用「无 bar」推断停牌。

---

## 5. 配置、夹具、文档触点

### 5.1 配置一览

| 旋钮 | 文件 | 动作 |
|------|------|------|
| `limit_rule` | `config/eval/costs.yaml` | → `board_calc_v1` |
| `limit_up_unfillable` | 同上 | 显式 `false` |
| `cost_version` | 同上 | bump |
| `hard_freeze_min_suspend_days` | `config/metrics/a_share_daily.yaml` | 新增，默认 20 |
| `param_version` | 同上 | bump |

### 5.2 测试夹具（最少集）

1. **hist board_calc：** `D < asof`、limit 空、有 `preclose_raw` → 写入 `limit_*` 且 `limit_source=board_calc_v1`。  
2. **asof 不填：** `D = asof` 缺 limit → 不写；fill 仍 `data_gap`。  
3. **不覆盖 vendor：** 已有 `em_*` → board_calc 跳过。  
4. **硬冻边界：** streak = N−1 → `flag=0`、无 forced_exit；streak = N ∧ `R` → `EXIT_RIGHT` / `forced_exit_untradable`。  
5. **空洞不计：** 中间缺 bar / 无 `flag_source` → streak 不跨洞虚增。  
6. **复牌清旗：** `is_suspended=0` → `hard_freeze_flag=0`。  
7. **costs：** YAML 含 `limit_up_unfillable: false`；loader 可读并传入 fill。  
8. **板幅：** ST 优先；`300`/`688` = 20%；主板 = 10%；raw 取整到分。

### 5.3 文档触点（落地时改）

- market-data-contract §5.2：启用路径；`hard_freeze_flag` 正式化；N 旋钮。  
- metrics §5.5：`hard_frozen` 并入旗；删「N 日后放」。  
- `todo.md` §2.5 / §2.6：标完成。  
- 本文件状态 → 已落地 + plan 链接（plan 另写）。

---

## 6. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-08 | 初版：Approach 1；hist board_calc + asof vendor；N=20 持久化冻旗；`limit_up_unfillable=false` 显式 |
