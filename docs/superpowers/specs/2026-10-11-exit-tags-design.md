# Spec：止盈辅助标签（开旗 + 只展示）

**日期：** 2026-10-11  
**状态：** 已落地；plan [`2026-10-11-exit-tags.md`](../plans/2026-10-11-exit-tags.md)  
**范围：** metrics §11 三标签（波动率放大 / 开香槟 / 危险信号）**已合入**（只展示；digest/Issue「止盈」列；个股三标签；L2 含 `danger`（合成 Σ 可用时，见篮 VOL）；L1 恒空）。yaml **`exit_tags_enabled=true`** / **`param_version=p05-v5`**（同 PR 篮 VOL Task 4 一次 bump）。  
**后放（禁止混入本 slice）：** fill / paper 减仓语义；L1 标签；`tag_rate_cap` 硬熔断日更；节气非线性打分；改 `R` / 右侧天数 / 节气 / 温度树 / RS / `VOL_score`；树外 bars 预热。  
**ops：** merge 后目标 `bars.db` 须硬冻 pass + 戳对齐 `p05-v5`（Protocol B）再跑 metrics。

交叉：metrics [`2026-09-29-trend-metrics-engine-design.md`](2026-09-29-trend-metrics-engine-design.md) §11 / §12 / §13 · Spec C [`2026-10-07-rs-c1-vol-design.md`](2026-10-07-rs-c1-vol-design.md) · 篮子 VOL [`2026-10-11-basket-vol-score-design.md`](2026-10-11-basket-vol-score-design.md) · 待办 [`todo.md`](../../../todo.md) P1 止盈辅助标签

产品对齐：专文「开香槟、危险信号、波动率放大」为**辅助止盈参考**；本 slice 只打标与展示，指标层右侧状态仍只由 \(T_{fsm}\) 驱动。

---

## 1. 问题

- `exit_tags_enabled` 默认 false；§11 三标签未实现；`tags[]` 契约在输出里有、库表无列。  
- 持仓/digest 无法看见止盈辅助信号；与公开语料「标签出现在品种下方」不对齐。  
- 若实现时误改 `R`/天数/节气，会破坏 FSM 真源（todo「不做」已钉）。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 架构 | **Approach 1**：指标管线末段纯函数写 `tags`；不碰 fill |
| 上线姿态 | **开旗** `exit_tags_enabled: true`；同 PR 终值 bump → **`p05-v5`**（与篮 VOL Task 4 一次收口；不要求中间 `p05-v4`） |
| Protocol B | bump 后须对目标 `bars.db` **重跑硬冻 pass + 写戳**（N 未变亦然）；否则 `daily_run` 戳校验失败（见 Protocol B §4.1） |
| 交易效力 | **只展示**；不改 fill / paper 仓位 |
| 实体 | **个股**三标签；**L2** `vol_expand` + `champagne` + **`danger`（合成 Σamount 可用且 `enable_l2_danger=True`）**；L1 恒 `tags=[]` |
| 稀疏度 | 观测 + 超 cap **stderr 告警**；本轮不硬熔断 |
| 文档拆分 | 与篮子 VOL **独立 Spec**；同 PR 串行本 Spec → 篮 VOL |

### 2.1 非目标

- 分仓减仓表、危险优先清仓等策略动作。  
- L1 `tags` 非空。  
- ~~**L2 `danger`**（合成尚无可靠 amount）~~ → **已由篮 VOL Spec 启用**（见 [`2026-10-11-basket-vol-score-design.md`](2026-10-11-basket-vol-score-design.md)）。  
- 新建侧表或旁路批处理 job。  
- 把标签嵌进温度/节气 FSM。  
- ~~本 slice 不实现篮子 `VOL_score`~~ → 同 PR 由姊妹 Spec 落地。

---

## 3. 方案

### 3.1 管线位置

在 `replay_metrics_cross_section` 内：peer RS、个股（及日后篮）`VOL_score` 赋值之后、upsert 之前，调用：

```text
scripts/metrics/exit_tags.py
  assign_exit_tags(stock_rows, l2_rows, l1_rows, *, params, bar_cache, l2_synth_by_code) -> rates_meta
```

- 入参：已算好的 asof 行 + 计算香槟/危险所需的历史窗（个股用 `bar_cache`；L2 用与 replay 同源的合成序列）。  
- 出参：只写各行 `tags`（`list[str]`，序列化见 §3.4）；`rates_meta` 供日志。  
- **禁止**函数内改写 `R` / 天数 / 节气 / `T` / `S_temp` / `RS` / `VOL_score`。

旗关：所有实体 `tags=[]`，不跑三标签逻辑（仍可写空列）。

### 3.2 三标签定义

参数键入 `config/metrics/a_share_daily.yaml` + `MetricsParams`（§13 初值）。生产 yaml：`exit_tags_enabled: true` / `param_version: p05-v5`；下列阈值键（及 `MetricsParams` 字段；**缺键则 load 失败**，含 `exit_tags_enabled`）：

| 键 | 初值 |
|----|------|
| `vol_expand_pctile` | 0.90 |
| `champ_k` | 3 |
| `champ_excess` | 0.05 |
| `danger_ret_pctile` | 0.05 |
| `danger_amt_pctile` | 0.95 |
| `tag_rate_cap` | 0.02 |
| `exit_tags_enabled` | **true**（`p05-v5`） |

| 稳定 id | 展示名 | 个股 | L2（已落地） |
|---------|--------|------|----------------|
| `vol_expand` | 波动率放大 | ✓ | ✓ |
| `champagne` | 开香槟 | ✓ | ✓ |
| `danger` | 危险信号 | ✓ | ✓（`enable_l2_danger` + 合成 Σamount 脊；否则不打） |

触发（全满足）：

| 稳定 id | 条件 |
|---------|------|
| `vol_expand` | `right_side` 真 **且** `solar_term ∈ {小暑,大暑}` **且** 当日 `sigma_pctile ≥ vol_expand_pctile` |
| `champagne` | 见下「香槟窗（钉死）」 |
| `danger` | 自身 `vol_hist` 窗内：日收益分位 ≤ `danger_ret_pctile` **且** 成交额分位 ≥ `danger_amt_pctile`（个股必算；L2 仅当 `enable_l2_danger` 且合成脊 amount 可用） |

**日收益：** 前复权收盘相对该实体 **OHLC/合成交易日脊**上前日：`close_t/close_{prev}-1`。脊 = 个股 `bar_cache` 序列 / L2 与 replay 同源的合成序列（合成省略日不在脊上）。

**香槟窗（钉死）：**

1. 取该实体脊上 **含 asof 在内的最近 `champ_k` 个交易日**（不足 `champ_k` → 不打）。  
2. **每一日**须：日收益有限 **且** > 该日宇宙收益中位数；任一失败 → 不打 `champagne`（不可算 = 断窗，**不**往前再凑日）。  
3. 窗内超额 `(ret - median)` 累加 ≥ `champ_excess`。

**宇宙中位数（香槟）— peer 集钉死为 (a) asof 冻结：**

| 实体 | 宇宙 | 中位数成员 |
|------|------|------------|
| 个股 | `local_stock` | **asof 日**满足 Spec C `stock_peer_eligible` 的代码集；用该**固定集合**在历史窗各日取收益（某成员该日收益不可算则**不计入该日中位数样本**；样本空 → 该日中位不可算 → 香槟失败） |
| L2 | `local_l2` | **asof 日**满足 `basket_peer_eligible` 的 L2 代码集；历史收益来自各码合成脊；其余同上 |

不要求对历史日重算 `RS_raw` / 逐日 peer 资格（Strategy A 仅物化 asof 行）。

**危险信号窗：** 与 VOL 相同交易日脊（个股 `bar_cache` / L2 合成脊）；窗长至多 `vol_hist`（含当日）；分位用与 Spec C §2.1 相同的 `percentile_rank` 语义（先得 \(p\in[0,1]\)，再与阈值比较）。当日收益或 amount 不可算 → 不打 `danger`。窗内有效收益样本或 amount 样本不足以定义分位（\(n\le 1\)）→ 不打。L2：wire 传 `enable_l2_danger=True`（篮 VOL 落地后）；否则 L2 永不打 `danger`。

**`vol_expand` 的 `sigma_pctile`：** 来自该实体 asof 特征（个股 / L2 合成 `replay_from_ohlc`）。实现须保证 asof 可得：在 `replay_from_ohlc` 把 `sigma_pctile` 拷进 snap（与 `S_temp` 同级；**今日未拷**），再经 ephemeral 行字段（如 `_sigma_pctile`）供 `assign_exit_tags` 读取，**upsert 前剥离**（不入 `COLS`）。不可算 → 不打 `vol_expand`。

**组合：** 一日可多标签；写出顺序固定：`vol_expand` → `champagne` → `danger`。缺特征 / 样本不足 → 跳过该标签，不抛错。

**L1：** 不计算；`tags=[]`。

### 3.3 稀疏度

- 按实体类分别计「标的·日」标签率：该行 `tags` 非空即计 1。  
  `rate = tagged_rows / eligible_rows`（eligible = 该类当日写入行数；分母 0 → 不告警）。  
- 若 `rate > tag_rate_cap`：stderr 一行 warn（含实体类、rate、cap、trade_date）；**不**使 `daily_run` 非零退出。  
- 本 slice **不**新增 `filters_meta` 列；`rates_meta` 仅日志/测试可断言。

### 3.4 存储

| 表 | 列 | 类型 | 语义 |
|----|-----|------|------|
| `daily_stock` / `daily_l2` / `daily_l1` | `tags` | `TEXT` | JSON 数组，如 `["vol_expand","champagne"]`；空为 `[]` |

- `ALTER` 入 `DAILY_*_ALTER_COLUMNS`；`COLS` 含 `tags`。  
- 内存行用 `list[str]`；upsert 前 `json.dumps(..., ensure_ascii=False)`。  
- 无侧表。

### 3.5 Digest / Issue

- 加列「止盈」（展示名顿号拼接；无标签 → 空）：  
  - 个股：**右侧存续 Top**、**今日温转热**（有行级 `daily_stock` 处）。  
  - L2：L1 Issue 内 L2 表、Radar 中带 L2 行处。  
- **L1 自身表 / L1 汇总行不加「止盈」列。**  
- 「今日温转平 / 结束右侧」事件表不加（非截面 `tags`）。  
- Radar / L1 Issue 正文随 digest 同源；不新开 Issue 类型。  
- 排序键不变。

展示名映射（钉死）：

```text
vol_expand → 波动率放大
champagne  → 开香槟
danger     → 危险信号
```

---

## 4. 数据流

```text
replay / peer RS / VOL_score
  → assign_exit_tags  (flag off → all [])
       stock: vol_expand + champagne + danger → tags[]
       L2:    vol_expand + champagne + danger（enable_l2_danger ∧ Σamount 脊）→ tags[]
       L1: []
       rates → optional warn
  → upsert daily_*（含 tags）
  → digest/Issue 渲染「止盈」列
```

（历史：止盈 Spec 单独验收时 L2 无 danger；同 PR 篮 VOL 后上式为准。）

---

## 5. 验收

| # | 断言 |
|---|------|
| 1 | 旗关夹具：`tags` 恒 `[]`；digest 无展示名 |
| 2 | 旗开金标：≥3 条命名序列分别命中三标签；负例不误触 |
| 3 | 不变式：打标前后 `right_side` / 天数 / `solar_term` / `T` / `RS` / `VOL_score` 逐字段相等 |
| 4 | L1 行 `tags=[]`；**仅本 Spec / 篮 VOL 未落地时**：L2 可有 `vol_expand`/`champagne`、**不得**含 `danger`；L2 香槟中位数来自 asof `local_l2` peer 集。**同 PR 已含篮 VOL 时**：以篮子 VOL 验收#8 为准（L2 可含 `danger`），本条「不得含 danger」不适用 |
| 5 | yaml：`exit_tags_enabled: true`；params 含全部 §3.2 键；**仅本 Spec 单独落地时** `param_version=p05-v4`。**同 PR 已含篮 VOL 时**：终值 `param_version=p05-v5`（一次 bump），本条不要求中间出现 `p05-v4` |
| 6 | digest 单测：右侧存续 Top / 温转热 / L2 表有标签行出现展示名；无标签空 |
| 7 | 超 `tag_rate_cap` 的夹具触发 warn 文案且进程退出码仍 0（单测 hook 捕获 stderr） |
| 8 | 香槟：脊上不足 `champ_k`、或窗内任一日收益/中位不可算、或未跑赢 → 不打；不向前凑日 |
| 9 | 运维/验收注：bump 后须 sync 硬冻 pass + 戳与 yaml `param_version` 一致（Protocol B），再绿 `daily_run` |

---

## 6. 文档与待办

- `todo.md` P1「止盈辅助标签」完成后改写为：已开旗、只展示、三标签已实现；减仓后放。  
- metrics 权威文 §11：本 slice 落地后加修订注「默认开；只展示；L1 空」并链本 Spec（避免与「默认关」旧句静默分叉）。  
- 姊妹 Spec 篮子 VOL：交叉引用；实现串行本 Spec → VOL（VOL 负责 Σ + 篮量分 + **启用 L2 `danger`**）。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-10-11 | 初版：Approach 1；开旗 p05-v4；只展示；个股+L2；三标签 §11；tag_rate 告警不熔断 |
| 2026-10-11 | CR：香槟断窗钉死；peer=(a) asof 冻结；L2 danger 后放；Protocol B 戳；digest 列落点；yaml 键表述修正 |
| 2026-10-11 | CR2：§4 数据流与 L2 无 danger 对齐；验收#4 加「仅止盈 slice / 同 PR 以篮 VOL#8 为准」 |
| 2026-10-11 | Plan CR：验收#5 同 PR 终值可为 p05-v5 |
| 2026-10-11 | Task 6（同 PR docs）：状态 → 已落地 (code)；metrics §11 修订注；todo 改写；yaml 开旗/pv 待 basket VOL Task 4 |
| 2026-10-11 | 篮 VOL Task 4：yaml 开旗 + `p05-v5`；状态 → 已落地；Protocol B ops 注 |
| 2026-10-11 | 完整 CR：§2/§3.2/§4 正文对齐同 PR 终态（L2 danger + p05-v5）；删 p05-v4 /「L2 不打」双源 |
