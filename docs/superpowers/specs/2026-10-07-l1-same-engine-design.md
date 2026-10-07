# L1 同引擎（C5 剩余）

**日期：** 2026-10-07  
**状态：** 设计已审；plan [`2026-10-07-l1-same-engine.md`](../plans/2026-10-07-l1-same-engine.md)  
**范围：** 仅一件事——L1 按 metrics §10.4 **成员闭包一次合成** → 与个股/L2 同一套温度/右侧/节气纯函数；行业自身温转热与成分密度拆开；`daily_l1.amount` 与密度同构 L2。digest/Radar 只做语义所需的最小对齐。  
**后放（禁止混入本 slice）：** L2/L1 全历史 replay 成本 / `engine_state` 增量；Spec C RS / Spearman / C1；Spec D 全 A / YAML 日拉；Spec E `board_calc` / 硬冻旗；假日 limit vendor 重拉；把合成 K 线写入 `bars.db`。

交叉：metrics [`2026-09-29-trend-metrics-engine-design.md`](2026-09-29-trend-metrics-engine-design.md) §6.0 / §10（C5 的 **L1 侧**）· L2 同引擎 [`2026-10-06-l2-same-engine-digest-design.md`](2026-10-06-l2-same-engine-digest-design.md) · market-data [`2026-10-01-market-data-contract-design.md`](2026-10-01-market-data-contract-design.md) §6.3 · taxonomy [`2026-09-28-industry-taxonomy-design.md`](2026-09-28-industry-taxonomy-design.md) · 待办 [`todo.md`](../../../todo.md) §2.1 / Spec B

---

## 1. 问题

§0 已把 **L2** 从 P0.5 interim（多数票 + tag-any）换成同引擎。**L1 仍走** `aggregate_l1` → `aggregate_members`：

- T = 闭包个股加权多数票  
- 右侧 = 成分 `right_side` 加权均值 ≥0.5  
- 节气 = 最重成分  
- **`tag_warm_to_hot` = tag-any**（任一成分 1 → 篮子 1）

metrics §10.4 要求：L1 = **成员闭包一次合成**（不先 L2 再嵌套），再调用与个股相同的纯函数。C5 的 L1 侧未闭合。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 范围 | **只做 L1 同引擎**；replay 性能 / 增量状态后放 |
| 路径 | Mirror L2 wire：闭包个股 bars → 合成 OHLC → `replay_from_ohlc` |
| 密度 / 成交额 | 与 L2 **同构**：个数=闭包内个股 `tag_warm_to_hot=1`；`amount`=闭包内个股 `amount` 非 null 求和（元） |
| digest / Radar | **最小语义对齐**（见 §5）；不大改产品形态 |

### 2.1 行业自身 vs 成分密度

| 字段 | 定义 |
|------|------|
| L1 `T` / `right_side` / `tag_warm_to_hot` / `tag_warm_to_flat` / `solar_term` | **L1 合成序列** → 与个股相同的 `compute_features` → 滞回 → FSM → 节气 |
| L1 `tag_warm_to_hot=1` | 仅当 **L1 自己**进入右侧（`ENTER_RIGHT`，进入日不另写 `WARM_TO_HOT`）或右侧内存续「温→热/沸」再确认（metrics §6.0） |
| `warm_to_hot_member_count` | asof 日截面中 **`ts_code ∈ YAML 闭包`** 且 `tag_warm_to_hot=1` 的行数（含 ST/停牌截面行；不要求进 tradable）。**不以**行上 `l1_id` 字段为准（避免未填/错填漏计；与合成候选同一成员集） |
| `amount` | asof 日同上（`ts_code ∈ YAML 闭包`）的 `amount` 非 null 求和；全缺 → NULL |

禁止再用 OR/tag-any 写入 `daily_l1.tag_warm_to_hot`。  
因此允许且正确：**T=凉、右侧=0、L1 温转热=0、成分温转热≥1**。

密度按 **个股** 计，**不按** 下属 L2 的行业温转热个数计。  
（L2 现码用 `sw_l2_code==code` 等价于「∈ 该 L2 的 YAML 成员」；L1 统一显式用闭包 `member_set`。）

### 2.2 明确不做

- 嵌套：先 L2 合成价再加权成 L1  
- 只改 tag、T 仍多数票（假 C5）  
- 持久化 `engine_state` / 截断 lookback「加速」  
- Spec C 的 `S_temp` / `RS`（本 slice **保持 NULL**）  
- 为 L1 写入 `signal_event`（开仓仍只认个股 `ENTER_RIGHT`）

---

## 3. L1 合成价（同引擎输入）

**候选成员：** `stub_l1_members()` / `member_closure`——该 `l1_id` 下属全部 L2 的 YAML 个股并集（taxonomy 映射宇宙）。实现上可把 `stub_l1_members` 重命名为更中性的 `l1_members_map`（同义，本 slice 允许）。

**禁止**把 asof 日 `tradable_rows`（`hard_frozen` / 停牌过滤后的当日截面）冻成整段历史成员集——今日 ST 不得改写历史指数。

对每个 L1、每个交易日 \(t\le D\)，成员资格与权重只读 **`bars` 当日行**。  
**公式真源** = L2 spec [`2026-10-06-l2-same-engine-digest-design.md`](2026-10-06-l2-same-engine-digest-design.md) **§3**（链式 close / HL 代理 / 夹紧 / 跳过日）；本文件不复述公式，避免双源漂移。摘要：

- 候选 ∩ 当日有 bar，且 `close_qfq` 有限且 >0，且 `is_st=0`，且 `is_suspended=0`
- 权重：market-data §6.3，`w_raw` 用 **当日 `bars.float_mv`**（缺/≤0 → 1.0），再对当日参与子集归一
- 「上一交易日」= 注入交易日历的前一日，不是该票上一根非空 bar
- \(R_t\) 空 → 该日不写合成 bar；asof 仍 upsert `daily_l1`，引擎字段 SQL NULL；`warm_to_hot_member_count` / `amount` 仍按 asof 个股截面
- `hard_frozen`：篮子固定 false；合成条 `is_st=0`、`is_suspended=0`
- 历史长度：成功合成 bar 行数 vs 与个股同一 `min_history` / `vol_hist` 门槛

### 3.1 实现落点

1. **合成函数：** 将 `synthesize_l2_bars` 提成篮子无关的 `synthesize_basket_bars`（或保留名作薄别名）。L2 与 L1 **共用**同一实现；**禁止**复制一份公式分叉。  
2. **asof 行构造：** 泛化 `_l2_asof_row` → 篮子无关 helper（`code` + YAML `member_set` + **全日个股截面 `stock_rows`** 计密度/金额；引擎列来自 snap 或 NULL）。L2/L1 共用。  
   - **必须**传入完整 `stock_rows`（与 L2 相同），**禁止**只传 `tradable_rows`（否则 ST/停牌被丢掉，违反 §2.1）。  
   - 密度/`amount`：**只**用 `ts_code ∈ member_set` 过滤（见 §2.1），不要另开 `l1_id==code` / `sw_l2_code==code` 分支。  
   - 共享 helper 把 L2 现码从 `sw_l2_code==code` 改为 `∈ member_set` 是 **故意等价收束**（YAML 成员为真源）；须同步修订 L2 spec（见 §9），禁止只改码不改 L2 文档。  
3. **`process_day` / `replay_metrics_cross_section` 顺序（钉死）：**  
   - 个股 replay →（调用方）upsert `daily_stock` / 个股 events  
   - 既有 L2 同引擎路径不变  
   - **`bar_cache`：** L1 **必须**复用本函数内 L2 已 preload 的同一 `bar_cache`；对 L1 闭包中尚未加载的 `ts_code`，按 L2 同款 `_load_symbol_bars(…, D)` **补拉**后再合成。**禁止**只拿 `universe` 入参里已有的 bars（闭包合成会偏短）。  
   - **然后**对每个 YAML 闭包非空的 L1：从 `bar_cache` 取成员 bars≤D → `synthesize_basket_bars` → `replay_from_ohlc` → 只持久化 asof 的 `daily_l1`  
   - YAML 闭包非空 → **必须** upsert 该 L1 行（引擎可全 NULL + 截面计数/金额）。**禁止**沿用现码 `if members_tradable` 过滤掉行。  
   - **禁止**再调用 `aggregate_l1` / `aggregate_members` **写** `daily_l1` 引擎列  
4. **禁止**把 L1 snap 的 `event_records` 送进 `append_signal_events`。  
5. **禁止**把 `L1.l1_health` 这类假代码写入 `bars.db`。  
6. `aggregate_l1` / `aggregate_members`：生产写路径断开后，可保留供单测 interim 对照或删除死代码——以「生产不调用」为验收线；若删，须同步改仍依赖它们的测试。

### 3.2 交易日历

与 L2 相同：`_l2_trade_dates`（或改名 `_basket_trade_dates`）= 从已加载 bars 最早日到 D 的 **完整交易日历**，不是 bar-union。L1 与 L2 **共享**同一 `dates` 列表与同一 `bar_cache`（见 §3.1#3）。

---

## 4. 表结构

`daily_l1` 已与 `daily_l2` 共享 `DAILY_BASKET_COLS` / `DAILY_BASKET_ALTER_COLUMNS`（含 `warm_to_hot_member_count`、`amount`）。本 slice **无强制新列**；验收是 **语义**从 interim → 同引擎，且密度/金额按 §2.1 填写。

| 列 | 本 slice |
|----|----------|
| `T`, `right_side`, `tag_warm_to_hot`, `tag_warm_to_flat`, `solar_term` | 同引擎 FSM；跳过日 → SQL NULL（**禁止** `_sql_int_bool(None)→0`；**禁止**省略键导致 ON CONFLICT 留旧值） |
| `warm_to_hot_member_count` | 闭包个股温转热个数；无命中截面时 0 |
| `amount` | 闭包个股额之和（元）；全缺 NULL |
| `S_temp`, `RS` | 保持 NULL |
| `members_tradable` / `members_total` | 保留：tradable=闭包内 asof 非 hard_frozen 且非停牌个数；total=YAML 闭包大小 |

`warm_to_hot_member_count` **不得**加入 `_INT_BOOL_COLS`。

`signal_event`：**不**为 L1 写入 `ENTER_RIGHT` / `WARM_TO_HOT` / `EXIT_RIGHT`。

`map_version` / `param_version`：沿用现有写入；不因本 slice 单独 bump `map_version`（归属未变）。

---

## 5. digest / Radar（最小对齐）

目标：避免把 **L1 FSM 温转热** 与 **个股温转热计数** 混称「同引擎」；不大改表结构。

### 5.1 L1 Issue（`render_l1_issue`）

在现有「行业（L2）扫描」**之前**，增加一小段。标题文案钉死为：

```text
## L1 自身
```

**禁止**写成「同引擎」「L1 同引擎」等（与 Radar 混称禁令一致；同引擎是实现事实，不是表头促销语）。

单行表：

```text
| T | l1_id | 名称 | RS | 右侧 | 节气 | 温转热 | 成分温转热 | 成交额(亿) |
```

- 数据来自 asof `daily_l1`（`code=l1_id`）  
- `名称` = `l1_buckets.yaml` 的 `name_zh`  
- `温转热` = L1 自身 `tag_warm_to_hot`；`成分温转热` = `warm_to_hot_member_count`（YAML 闭包口径，§2.1）  
- `RS` / 引擎空值：SQL NULL → 单元格 **空**（**禁止**渲染成 `0`）  
- `成交额(亿)` = `amount/1e8` 的 `%.3f`（NULL→空），与 L2 渲染一致  
- 无 `daily_l1` 行 → 引擎列空，不崩

其下 L2 扫描 / 个股温转热 Top 等 **保持 §0 已落地形态**（个股表仍按 `daily_stock.l1_id` 过滤——见 §5.2）。

### 5.2 Radar「按 L1」与「允许不一致」

现表：

```text
| L1 | l1_id | T* | 个股 | 右侧 | 右侧占比 | 温转热 |
```

钉：

- `温转热` **仍是个股 tag 计数**（按 `daily_stock.l1_id` 过滤，现实现），**不是** `daily_l1.tag_warm_to_hot`，也**不是** `daily_l1.warm_to_hot_member_count`。表头改为 **`个股温转热`**。  
- `T*` **仍是个股截面摘要**（现实现不改为 `daily_l1.T`）。脚注钉死：  
  `T* / 个股温转热 = 个股截面（按 l1_id），非 L1 同引擎；L1 自身（含 YAML 闭包「成分温转热」）见各 L1 Issue「L1 自身」。`  
- **允许不一致（钉死）：** Issue「L1 自身」的「成分温转热」（YAML 闭包）与同 Issue 个股表 / Radar「个股温转热」（`l1_id` 过滤）**不必相等**（行上 `l1_id` 错填/空、或与 YAML 短暂不一致时）。**禁止**为刷齐这两个数而改口径或互抄。  
- **禁止**把 Radar 的 `T*` 或「温转热」改名义冒充 L1 同引擎而不改数据源。

### 5.3 不做

- 不重做 L2 扫描表头（已同引擎）  
- 不在本 slice 拉新中文名 / 改 YAML 归属  
- 不要求 Radar 主表改为展示 `daily_l1.T`  
- 不要求把 Radar / 个股 Top 的过滤从 `l1_id` 改成 YAML 闭包（那是展示一致性战役，后放）

---

## 6. 错误处理

| 情况 | 行为 |
|------|------|
| 闭包全日无收益 / \(R_t=\emptyset\) | 跳过该日合成 bar；引擎 NULL；密度/金额仍按截面 |
| 缺 high/low | 该日 H=L=P |
| YAML 闭包为空 | 与 L2 相同：`continue`，**不** upsert 该 L1 行 |
| 合成夹紧失败 | 该日当跳过 bar |
| asof 无 snap | upsert 行：引擎 NULL + 截面计数/金额 |
| 性能变慢（+14 次全历史 replay） | **接受**；禁止裸砍 lookback；增量状态另开 slice |

---

## 7. 测试（Done when 的可测子集）

1. **`test_C5_same_engine_on_synthetic`（L1 侧）：** 两只完全相同的人造 OHLC、等权，闭包只含这两只 → L1 的 `T`/`right_side`/`tag_warm_to_hot`/`tag_warm_to_flat`/`solar_term` 与单只 `replay_from_ohlc` 在 asof 一致。（L2 侧回归必须继续绿。）夹具须同时 stub `l2_members_map` **与** `l1_to_l2` / `stub_l1_members`（或等价），否则闭包为空测不到。  
2. 多数票凉 + 一只成分 tag=1 → `daily_l1.tag_warm_to_hot=0` 且 `warm_to_hot_member_count=1`（计数输入为全日 `stock_rows`，含非 tradable）。  
3. **密度口径夹具（锁 CR#2，禁止只靠散文）：**  
   - 票在 YAML 闭包内，但行上 `l1_id` / `sw_l2_code` 错或空，且 `tag_warm_to_hot=1` → **仍计入**该 L1 的 `warm_to_hot_member_count`；  
   - 票**不在**闭包，仅 `l1_id`（或其它字段）命中且 tag=1 → **不计**；  
   - 下属 L2 的 `daily_l2.tag_warm_to_hot=1` **不得**计入 L1 密度（只计个股）。  
4. **反嵌套（必有运行时自动化；禁止仅 grep/文档断言过关）：**  
   - L1 合成输入成员集 = `member_closure`；  
   - 生产路径**不**读取 `daily_l2` 价格序列来拼 L1；  
   - 生产路径**不**调用 `aggregate_l1` 写库——须用 spy/monkeypatch 或等价 **运行时**断言（可另加源码扫描，但不能只靠扫描）。  
5. 跳过日：asof \(R_t=\emptyset\) → 引擎字段 SQL NULL（不是 0），密度/`amount` 仍可有值；且 **`members_tradable=0` 仍有 `daily_l1` 行**。  
6. digest：标题精确为 `## L1 自身`；表含成分温转热；RS NULL→空；Radar 表头为「个股温转热」且脚注含「按 l1_id」与「L1 自身」指向。  
7. **L2 回归：** 共享 synth/asof 重构后，既有 L2 C5 / L2 wire / 跳过日 / 密度拆列测试全绿；L2 `warm_to_hot_member_count` 在「YAML 成员 vs 错 `sw_l2_code`」夹具下仍按 `member_set`（与本 slice 收束一致）。  
8. **不要求** RS / Spearman / C1、9.30 limit 重跑、L2 replay 性能、增量 `engine_state`、Radar 与「L1 自身」成分温转热数值刷齐。

---

## 8. 非目标 / 后放

- L2/L1 replay 成本与增量状态  
- RS peer / `test_C1` / Spearman（Spec C）  
- 未映射全 A、YAML 日拉（Spec D）  
- `board_calc`、硬冻旗（Spec E）  
- 合成 K 线入 `bars.db`  
- 改 `evaluate_ok` / Ops A 软门禁  
- 把 Radar 主表改成 L1 同引擎温度主展示

---

## 9. 文档同步（本 slice Done when）

- 本文件状态 → 已落地 + plan 链接  
- `todo.md`：Spec B 标记完成；§2.1 勾掉  
- `README.md`：L1 same-engine shipped；Still out 去掉 same-engine L1  
- **L2 spec 必须同 commit 修订**（避免双真源），至少包括：  
  1. 「L1 / `aggregate_l1` 保持 interim」「禁止给 L1 填写温转热个数/金额」→ 标注 **已被本 Spec B 取代**；L1 由本文件定义。  
  2. L2 密度/`amount` 口径：由「`sw_l2_code` 命中」改为（或等价注明）**`ts_code ∈ 该 L2 的 YAML 成员集`**；实现可与共享 asof helper 对齐。  
  3. 「禁止调用 `aggregate_l1` 写 L2」句保留；删除「`aggregate_l1` 保持现状」作生产真源。

---

## 10. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-07 | 初稿：路径 Mirror L2；密度/金额同构；digest 最小对齐；性能后放 |
| 2026-10-07 | CR：钉 `member_set` 密度口径、全日 `stock_rows`、禁 `members_tradable` 丢行；反嵌套必自动化；公式真源=L2 §3 |
| 2026-10-07 | subagent CR：密度夹具；bar_cache 复用/补拉；digest 允许不一致；L2 文档同步清单；反嵌套须运行时断言；标题/RS 空值钉死 |
