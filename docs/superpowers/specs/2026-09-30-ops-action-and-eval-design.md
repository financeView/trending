# 运维落地与可回测评估设计

> 状态：草案  
> 日期：2026-09-30  
> 参考：同目录 `economy-strategy/spec-daily-quant.md`（Actions + SQLite 事实源 + 交易日历门禁 + 幂等重跑 + Issue 看板）  
> 依赖：  
> - [`2026-09-28-industry-taxonomy-design.md`](./2026-09-28-industry-taxonomy-design.md)  
> - [`2026-09-29-trend-metrics-engine-design.md`](./2026-09-29-trend-metrics-engine-design.md)  
> - [`2026-10-01-market-data-contract-design.md`](./2026-10-01-market-data-contract-design.md)（日历 / bars / 涨跌停缺失 / float_mv / 断点续跑）  
> 非目标（本期）：Web/小程序页面；算法稳定后再做。

## 1. 目标

每个**A 股交易日**收盘后自动：

1. 拉取/更新行情缓存 → 跑分类归属 + 指标引擎  
2. 结果写入 SQLite（`data/trend.db`）并 **commit 回仓库**  
3. 按 **L1 一级分类** 各维护 **1 个长期 Issue**，覆盖写入当日摘要  
4. 支持指定交易日 **重跑**（幂等覆盖）  
5. 历史截面可支撑 **信号回放 / 简易账本回测**（评估难点的工程底座）

## 2. 总体架构（对齐 economy-strategy）

```text
GitHub Actions (cron 工作日 北京 19:00 + workflow_dispatch)
  └─ checkout（含 data/trend.db）
  └─ cache 恢复 data/cache/bars.db（gitignore，不 commit）
  └─ 交易日历门禁：非交易日 exit 0，不写库、不改 Issue
  └─ 断点续跑：待跑交易日 = next_trade_date(last_ok) … session_asof（asof=最近交易日，不是 --date）
  └─ scripts/daily_run.py [--date D [--only-date]]   # --date=重跑起点；cron 不传
        ├─ sync bars（可算宇宙；须含当日 open_raw 等成交字段）
        ├─ upsert stock_sw_l2 / 合成 L2·L1
        ├─ metrics engine → 截面 + 事件
        ├─ update L1 Issues（14 个）
        └─ P2: live_shadow_step(T)  # 仅当 run_meta(T)=ok；fill_day(T, prev_trade signals)；否则 skip+warn
  └─ commit data/trend.db (+ heartbeat)  rebase-retry push
```

行情源、`limit_*` 缺失、`float_mv`、分批回填：**一律以** [`2026-10-01-market-data-contract-design.md`](./2026-10-01-market-data-contract-design.md) 为准。
### 2.1 目录布局

```text
trending/
├── .github/workflows/daily-trend.yml
├── config/
│   ├── taxonomy/          # l1_buckets.yaml, sw_l2_to_l1.yaml, display_groups.yaml
│   ├── metrics/a_share_daily.yaml
│   └── eval/costs.yaml    # 纸面/影子成本；见 backtest-eval §4.3
├── fixtures/              # temp_raw_gold.csv, fsm_*.json
├── scripts/
│   ├── common/            # db.py, calendar.py, market_client.py, git_commit.py
│   ├── daily_run.py
│   ├── update_l1_issues.py
│   └── eval/              # replay / paper_book（可后置同一仓库）
├── data/
│   ├── trend.db           # ✅ commit：只存计算结果 + 元数据
│   ├── heartbeat.json     # ✅ commit：最近一次成功摘要
│   └── cache/bars.db      # ❌ gitignore：日线缓存；Actions cache 持久化
├── tests/
└── docs/superpowers/specs/
```

### 2.2 存储原则

| 存什么 | 哪里 | 是否 commit |
|--------|------|-------------|
| 日截面指标、事件、运行元数据 | `trend.db` | 是 |
| 原始/复权日线 | `cache/bars.db` | 否（体积） |
| 映射/参数版本字符串 | `trend.db.run_meta` + git 里 YAML | 是 |

估算：全 A ~5000 可算标的 × 1 行/日 + L2/L1 百余行 → 年增量远小于「全量 K 线进 git」；须监控 `trend.db` 体积，必要时按年分库或 git-lfs（后话）。

## 3. 调度与重跑

### 3.1 Workflow

权威输入与三种跑法见 [`2026-10-05-sw-yaml-universe-design.md`](2026-10-05-sw-yaml-universe-design.md) §3.1。实现用 `date`（不是旧稿 `trade_date`）+ `only_date`：

```yaml
on:
  schedule:
    - cron: '0 11 * * 1-5'   # 北京 19:00（UTC 11:00）
  workflow_dispatch:
    inputs:
      date:                 # 重跑起点 YYYY-MM-DD；空=cron 语义（asof=最近交易日，无 --date）
        required: false
      only_date:
        type: boolean       # true=只跑 D；false=从 D 追到 asof
        default: false
      force_trade_day:
        type: boolean
        default: false
concurrency:
  group: daily-trend
  cancel-in-progress: false
```

- cron：不传 `date`；sync `--end`=`latest_trade_day()`；`--with-limits`；`daily_run` 无 `--date`。
- `date=D` + `only_date`：sync `--end D`；`daily_run --date D --only-date`。
- `date=D` 无 only_date：sync `--end`=最近交易日；`daily_run --date D`。
- `sync_complete` 必须进 `GITHUB_OUTPUT`（不能只靠日志）。false 则 **跳过** daily_run / L / commit trend.db。
- 上海「今日」一律 `latest_trade_day()`，不是民用日历 `date`。

### 3.2 交易日门禁

- 脚本用交易日历（与 economy-strategy 同源思路：新浪/数据商 hist）判断。  
- 非交易日：`exit 0`，日志 `[skip] non-trading-day`，**不** commit、**不**改 Issue。  
- `--force-trade-day` 仅测网/单测。

### 3.3 幂等重跑

- 所有结果表主键含 `trade_date`（+ 实体键）——**下表例外除外**。  
- 同日重跑对 **`run_meta` / `daily_stock` / `daily_l2` / `daily_l1`** = **UPSERT 覆盖**（或先 DELETE 这些表该日行再写入）。  
- **`signal_event`：append-only**。重跑日 D 若事件内容变了 → **插入新行**（新 `id`），旧行保留并设 `superseded_by=新id`；**禁止**物理删除已被 `paper_fill.signal_event_id` 引用的行。  
- **`paper_fill`：immutable**。`daily_run` / 重跑 **不得** DELETE/UPDATE 已有行；仅 `live_shadow_step` 追加新行。  
- 重跑**不**删除他日 `daily_*`；FSM 路径依赖 → 重跑日 \(T\) 须从上一交易日状态或 bars 全日重算恢复。  

**强制约定（评估正确性）**：

> 对任意 `trade_date=D` 的正式截面结果，必须由「仅使用 ≤D 的 bars + 冻结的 `param_version`/`map_version`」因果重算得到。  
> 支持两种实现（MVP 选一，写进代码注释）：  
> **A. 全日重放（推荐 MVP）**：每次 daily_run 对可算宇宙从足够历史窗口滚动重算到 D（状态不持久化依赖脏状态）；截面只 upsert D。  
> **B. 增量状态表**：持久化每标的 `engine_state`；重跑 D 时先回滚 D 日事件再从 D-1 状态步进——实现难，易脏。  

MVP 采用 **A**：牺牲一点 CPU，换重跑语义干净。事件与影子成交的不可变规则见上，**不以 A 为借口覆盖 `signal_event`/`paper_fill`**。

## 4. 库表（逻辑最小集）

```text
run_meta (
  trade_date PK,
  param_version, map_version, member_set,
  universe_size, unmapped_count, tradable_count,
  bar_coverage REAL,           -- 见 market-data-contract §7.2
  computable_coverage REAL,
  limit_coverage_asof REAL,
  open_raw_coverage_asof REAL,
  mapped_size INTEGER,         -- |load_universe_codes()|
  mapped_sync_coverage REAL,   -- 映射宇宙当日 bar+flag / mapped_size
  ok_predicate_version TEXT,   -- v1.1+
  git_sha, started_at, finished_at, status, warn TEXT
)

daily_stock (
  trade_date, ts_code,
  sw_l2_code, l1_id,
  T, S_temp, RS, universe_id,
  right_side, right_side_days_natural, right_side_days_trading,
  tag_warm_to_hot, tag_warm_to_flat, solar_term,
  hard_frozen,             -- metrics §5.5；MVP=is_st∨显式硬冻旗
  amount,
  close_qfq,               -- 信号/展示用前复权收盘；盯市用 bars.close_raw
  float_mv,                -- 可空；当日同步写入；历史回填禁 spot 回刷；缺省权重见 market-data §6.3
  PRIMARY KEY (trade_date, ts_code)
)

daily_l2 / daily_l1 (
  trade_date, code,
  T, S_temp, RS, right_side, ..., members_tradable, members_total,
  PRIMARY KEY (trade_date, code)
)

signal_event (              -- 回测/审计；L 轨锚定 id
  id INTEGER PK,            -- 稳定主键；已消费于 paper_fill 的行不得物理删除
  trade_date, ts_code, l1_id, sw_l2_code,
  event TEXT,              -- ENTER_RIGHT | EXIT_RIGHT | WARM_TO_HOT（映射见 metrics §6.0）
  T, RS, detail TEXT,      -- EXIT_RIGHT 时 detail.exit_kind=temperature|forced_exit_untradable
  superseded_by INTEGER NULL  -- 重跑产生替代事件时指向新 id；旧行保留
)

-- paper_fill：MVP 落在 trend.db（随库 commit）；字段见 backtest-eval §4.7
-- live_shadow/ 仅摘要；重跑不得改写已有 paper_fill（§3.3 + backtest-eval §4.10）
```

**`paper_fill`（MVP 必建，非可选）**：表在 `data/trend.db`，随日常 commit；字段与不可变规则见 backtest-eval §4.7 / §4.10。`output/eval/live_shadow/` 只写当日 snip，不作唯一事实源。

## 5. L1 Issues（无页面阶段的「人机界面」）

### 5.1 约定

- **每个 `l1_id` 固定 1 个 Issue**（共 14 个），标题如：`[L1] 医药健康 (l1_health)`。  
- Issue body **整页覆盖**为当日（或指定重跑日）报告，顶部钉：`as_of`、`param_version`、`map_version`、运行链接。  
- 另可选 1 个总览 Issue：`[Radar] A股战场`（右侧占比、温转热个数、按 L1 排序）。  

创建策略：仓库 settings 记下 issue number，或首次跑用 label `l1-dashboard` + title 精确匹配查找，没有则 create。

### 5.2 单 L1 Issue 内容骨架

```markdown
# {L1名} · {trade_date}

meta: param=… map=… run=…

## 行业（L2）扫描
| T | 名称 | RS | 右侧 | 节气 | 温转热 | 成交额 |
|…|

## 今日温转热（个股，Top N by 成交额）
…

## 今日温转平 / 结束右侧
…

## 右侧存续 Top（RS 高）
…
```

排序：L2 按 `rank(T)` 再 `S_temp`；个股列表默认成交额。

### 5.3 权限与噪音

- `issues: write`；失败时 webhook（可选，同 economy-strategy）。  
- 非交易日不更新 Issue，避免「假日报」。

## 6. 评估与回测

**完整回测 / 成交 / 主规则**见：  
[`2026-09-30-backtest-eval-design.md`](./2026-09-30-backtest-eval-design.md)

本运维文档只提供评估底座：

- 每日 upsert 截面 + `signal_event`（`ENTER_RIGHT` / `EXIT_RIGHT` / `WARM_TO_HOT`；映射见 metrics §6.0）  
- `run_meta` 钉死 `param_version` / `map_version`  
- 因果重算策略 A（§3.3），保证历史日可重放  
- P2 起可选 `live_shadow_step`（影子账本，非真钱）

摘要：层 A 工程门禁 → 层 B 信号前瞻 → 层 C 历史纸面（**出：温转平，不是回落至温**）→ 层 L 上线后影子。  
执行细节（成本、涨跌停、组合、`paper_fill`、walk-forward）见 backtest-eval **§4**。  
**不是**「只统计上线后实盘收益」。

## 7. 与指标 / 分类 spec 的衔接

- 宇宙、`members_tradable`、L1 闭包：分类树。  
- \(T\)/RS/右侧/节气：指标引擎；`param_version` 来自 metrics YAML。  
- Issue 按 L1 切分：直接消费 `daily_stock.l1_id` / `daily_l2`。  
- 危险信号默认关：不进 Issue 主列表，除非 flag 开。

## 8. 分期

| 期 | 内容 |
|----|------|
| **P0** | 日历门禁 + bars sync 骨架 + daily_run（重算策略 A）+ `run_meta` §7.2 `ok` + trend.db commit + 金标 loader/单测；**不含**完整 T 树/滞回/FSM/节气（见 plan：FSM 属 **P0.5+**） |
| **P0.5** | T_raw 决策树 + 滞回 + 右侧 FSM + 节气线性式 + 命名夹具；**计算并落库** `daily_*` 与 `signal_event`（§6.0 枚举）；Issue 仍属 P1 |
| **P1** | 14 个 L1 Issue + 总览 Radar Issue（消费已落库截面/事件）；可选影子闸门对齐 |
| **P2** | 回测 spec：层 B 周报 + 层 C 纸面 + 层 L 影子（见 backtest-eval） |
| **P3** | 页面（另开 UX spec） |

## 9. 验收（按期）

**P0**

1. 本地默认 asof（`latest_trade_day()`，不传 `--date`）跑通；`run_meta` 有当日行与覆盖率字段；bars schema/sync 骨架可用。历史补洞用 `--date D --only-date`。  
2. **不要求**完整 `daily_stock` T/FSM 列（可为缺省/stub 或仅写 `run_meta`）；正式截面属 P0.5。  
3. 假日 workflow 一次：跳过且无空 commit。  
4. `workflow_dispatch` 指定历史某日可覆盖重算（至少 `run_meta`）。  
5. `pytest` 离线绿（日历 / ok 谓词 / 金标 loader）。

**P0.5**

1. 可算宇宙写出 `daily_stock` / `daily_l2` / `daily_l1`；同日重跑行内容稳定。  
2. `signal_event` 按 metrics §6.0 落库（含 `ENTER_RIGHT` / `EXIT_RIGHT` / `WARM_TO_HOT`）。  
3. FSM/节气命名夹具全绿。

**P1**

1. 14 Issue 更新成功，正文含 as_of 与温转热表。  
2. 抽 3 只股人工看图：热/温与均线直觉不离谱（定性，非贴趋势动物）。

层 L：`live_shadow_step` 仅当意图日 `run_meta.status=ok`（见 market-data §7.2 / backtest §4.6）。

## 10. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-09-30 | 初稿：Actions/db/Issue 对齐 economy-strategy；评估三层 + 成交语义锁定 |
| 2026-09-30 | 回测评估拆至 `2026-09-30-backtest-eval-design.md`；§6 改为引用 |
| 2026-09-30 | `paper_fill` / 执行契约指向 backtest-eval §4 |
| 2026-09-30 | 流水线接入 live_shadow_step；signal_event 不可变 / superseded_by |
| 2026-09-30 | §3.3 例外：daily_* UPSERT；signal_event append；paper_fill 必建于 trend.db 且不可变 |
| 2026-10-01 | 依赖 market-data-contract；cron 19:00；断点续跑按 next_trade_date(last_ok) |
| 2026-10-01 | cron 改为 UTC 11:00；run_meta 覆盖率字段；daily_stock.float_mv |
| 2026-10-01 | 跨 spec：P0 对齐 plan（FSM→P0.5）；`close_qfq`/`hard_frozen`；事件枚举指 metrics §6.0 |
| 2026-10-01 | P0.5 落库事件；§9 按期验收；L 闸 `run_meta=ok` |
| 2026-10-05 | `--date` 是重跑起点不是 session asof；见 sw-yaml-universe spec |
