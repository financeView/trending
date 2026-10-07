# L2 同引擎 + Issue 中文名 / 成交额亿元

**日期：** 2026-10-06  
**状态：** 已落地；plan [`2026-10-06-l2-same-engine-digest.md`](../plans/2026-10-06-l2-same-engine-digest.md)  
**范围：** 仅三件事——（1）L2 同引擎温度/右侧/节气/行业温转热，并与成分温转热密度拆开；（2）Issue 表保留代码列、新加中文名称列；（3）成交额按亿元、三位小数展示。  
**后放（禁止混入本 slice）：** L1 同引擎；未映射全 A；RS peer / Spearman / C1；成分 YAML 日拉；`board_calc`；假日 asof/limit → `partial`；因果 H / WF。

交叉：metrics [`2026-09-29-trend-metrics-engine-design.md`](2026-09-29-trend-metrics-engine-design.md) §6.0 / §10（C5 的 **L2 侧**）· market-data [`2026-10-01-market-data-contract-design.md`](2026-10-01-market-data-contract-design.md) §6.3 · ops [`2026-09-30-ops-action-and-eval-design.md`](2026-09-30-ops-action-and-eval-design.md) §5.2 · taxonomy [`2026-09-28-industry-taxonomy-design.md`](2026-09-28-industry-taxonomy-design.md) · 待办 [`todo.md`](../../../todo.md) §0

---

## 1. 问题

现行 `aggregate_members`（P0.5 interim）：

- T = 成分 `float_mv` **加权多数票**
- 右侧 = 成分 `right_side` 加权均值 ≥0.5
- 节气 = 权重最大且有节气的成分
- **`tag_warm_to_hot` = 任意一只成分 tag=1（tag-any）**

Issue「行业（L2）扫描」把篮子 T 和 tag-any 写在同一列「温转热」，出现 **T=凉、右侧=0、温转热=1**（例：Issue #1 `370100`，实际只有 `300016.SZ` 带 tag）。这不是行业 FSM 事件。

名称列写 6 位码；个股只有 `ts_code`；成交额用元的科学计数。

---

## 2. 目标口径

### 2.1 行业自身 vs 成分密度（必须拆开）

| 字段 | 定义 |
|------|------|
| 行业 `T` / `right_side` / `tag_warm_to_hot` / `tag_warm_to_flat` / `solar_term` | **L2 合成序列**走与个股相同的 `compute_features` → `decide_t_raw` → 滞回 → FSM → 节气 |
| 行业 `tag_warm_to_hot=1` | 仅当 **L2 自己**进入右侧（`ENTER_RIGHT`，进入日不另写 `WARM_TO_HOT`）或右侧内存续「温→热/沸」再确认（metrics §6.0） |
| `warm_to_hot_member_count` | asof 日截面中 **`ts_code ∈ 该 L2 的 YAML 成员集`** 且 `tag_warm_to_hot=1` 的行数（含 ST/停牌截面行；不要求进 tradable）。不以行上 `sw_l2_code` 字段为唯一真源（YAML 成员集为准；与共享 asof helper 对齐） |

禁止再用 OR/tag-any 写入 `daily_l2.tag_warm_to_hot`。  
因此允许且正确：**T=凉、右侧=0、行业温转热=0、成分温转热=1**。

L1：**本 slice 历史范围不改 L1**；L1 同引擎 / `daily_l1` 密度与金额见 [`2026-10-07-l1-same-engine-design.md`](2026-10-07-l1-same-engine-design.md)（**取代**下文已删除的「禁止给 L1 填个数/金额」「`aggregate_l1` 保持现状」作生产真源）。Radar「按 L1」的个股温转热计数仍按个股截面，表头不得写成「同引擎」。

### 2.2 中文名

- **L2：** `config/taxonomy/sw_l2_to_l1.yaml` 已有 `name_zh`。Issue **保留代码列**，**新加名称列**（只写中文，不把码拼进名称）。
- **个股：** `config/taxonomy/stock_sw_l2.yaml` 每条成员加可选 `name_zh`。Issue **保留 `ts_code` 列**，**新加名称列**。
- 缺 `name_zh` → 名称列 **空字符串**；代码列照写。不挡 digest、不挡 `run_meta`。
- 名称 **不落** `daily_stock` / `daily_l2`（渲染层 join YAML）。

个股名称源：东财 clist `f12`（6 位）+ `f13`（`1`→`.SH`，其它→`.SZ`，与 `em_client._infer_ts_code` 一致）+ `f14`（简称）**一次性**写入 YAML，与成分快照一起 check-in。只更新已有 `members` 行的 `name_zh`，不因 clist 多票而扩大宇宙。**不**做每日 cron 拉名；**不**在渲染时现拉网络。

**Loader / 写盘（钉死）：**

- `load_stock_sw_l2` 必须透传可选 `name_zh`（现码只抄 `ts_code`/`sw_l2_code`，会静默丢掉名称）。
- **禁止**用现有 `fetch_sw_members.dump_yaml` 回填名称（它只写出 `{ts_code, sw_l2_code}`）。另做「patch existing members」的 updater。

### 2.3 成交额亿元

- 库内仍存 **元**（`REAL`）。
- Issue 展示：`亿元 = amount / 1e8`，格式 `%.3f`（三位小数）。
- `amount` 为 SQL NULL → 成交额列 **空**（不写 `0.000`）。
- L2 `amount` = asof 日 **`ts_code ∈ 该 L2 YAML 成员集`** 的 `amount` **求和**：只加非 null（含 ST/停牌截面行）；全缺 → NULL。禁止把合成指数的「成交额」另编一套。

---

## 3. L2 合成价（同引擎输入）

YAML 候选成员：`l2_members_map()` 中该 L2 的 `ts_code` 列表（taxonomy 映射宇宙）。

**禁止**把 asof 日 `tradable_rows`（`hard_frozen` / 停牌过滤后的当日截面）冻成整段历史成员集——今日 ST 不得改写历史指数。

对每个 L2、每个交易日 \(t\le D\)，成员资格与权重只读 **`bars` 当日行**：

- 候选 ∩ 当日有 bar，且 `close_qfq` 有限且 >0，且 `is_st=0`，且 `is_suspended=0`
- 权重：market-data §6.3，`w_raw` 用 **当日 `bars.float_mv`**（缺/≤0 → 1.0），再对 **当日参与该步的子集** 归一。禁止用 asof `daily_stock.float_mv` 回刷历史日；禁止今日 spot 回刷。

「上一交易日」= `prev_trade_date(t)`（交易日历），**不是**该票上一根非空 bar。缺日历上一日 close → 该票不进当日收益集。

**收益子集 \(R_t\)：** 上款成员中，日历上一交易日 `close_qfq` 也有限且 >0 者。

**相对高低子集 \(M^H_t\)：** 上款成员中，当日 `high_qfq`（或 `high`）、`low_qfq`（或 `low`）、`close_qfq` 均有限且 close>0 者。

1. **链式 close。** 若 \(R_t\) 非空：

   \[
   r_t = \sum_{i \in R_t} w_i \left(\frac{c_{i,t}}{c_{i,t-1}} - 1\right)
   \]

   权重 \(w_i\) 只在 \(R_t\) 上按当日 `float_mv` 归一。令 \(P_{\mathrm{prev}}\) 为该 L2 **最近一次成功合成日** 的 close（中间跳过日不重置指数）。

   \[
   P_t =
   \begin{cases}
   1+r_t & \text{尚无 } P_{\mathrm{prev}}\\
   P_{\mathrm{prev}}\,(1+r_t) & \text{否则}
   \end{cases}
   \]

   若 \(P_t\) 非有限 → 该日当跳过 bar（不更新 \(P_{\mathrm{prev}}\)）。行业单日 \(r_t\le-1\) **不**作为设计门闩。

2. **high/low 代理。** 若 \(M^H_t\) 非空：

   \[
   \bar h_t = \sum_{i \in M^H_t} w'_i \frac{h_{i,t}}{c_{i,t}},\quad
   \bar \ell_t = \sum_{i \in M^H_t} w'_i \frac{\ell_{i,t}}{c_{i,t}}
   \]

   \(w'_i\) 只在 \(M^H_t\) 上归一。合成 \(High_t=P_t\cdot\bar h_t\)，\(Low_t=P_t\cdot\bar \ell_t\)。  
   若 \(M^H_t\) 空：\(High_t=Low_t=P_t\)。

3. **夹紧。** \(Low_t=\min(Low_t,P_t,High_t)\)，\(High_t=\max(Low_t,P_t,High_t)\)；三者均须 >0。若夹紧后仍非法 → 该日不写合成 bar。

4. **跳过日。** \(R_t\) 空 → **不**把该日写入送给 `replay_from_ohlc` 的 OHLC 序列（不把 \(P\) 平移充数；序列里缺日，由现有 `natural_bump_after` 盖日历缝）。FSM **不**在跳过日 step（无 §5.5 填温度）。  
   asof 恰为跳过日时：仍 upsert 一行 `daily_l2`，引擎字段 `T`/`right_side`/`tag_*`/`solar_term` 必须是 **SQL NULL**（**禁止** `_sql_int_bool(None)→0`；**禁止**省略这些键——`upsert` 在 ON CONFLICT 时只更新 row 里出现的列，省略会留下旧值；也禁止「无 snap 就不写 L2 行」）；`warm_to_hot_member_count` 与 `amount` 仍按 asof 个股截面计。

5. **`hard_frozen`：** L2 固定 `false`（篮子无 ST）。送入 `replay_from_ohlc` 的合成条 `is_st=0`。

6. **历史长度：** `compute_features` 看的是 **成功合成 bar 的行数**（与个股同一 `params.min_history_temp` / `vol_hist` 门槛；测试可用与个股相同的缩短 params）。不足则该日 `computable=False`，温度不可算，不进入右侧。缺 high/low 时用 H=L=P，满足特征层对 high/low 列的要求。

7. **落地路径：** `process_day` 先重放个股截面并 upsert `daily_stock` / 个股 `signal_event`。然后对 **每个 YAML 非空成员列表的 L2**（不论 asof 是否有可合成 bar）用成分 **bars≤D** 按上款合成全序列 → `replay_from_ohlc`（序列可空）→ 只持久化 asof 的 `daily_l2`（可全为引擎 NULL + 截面计数/金额）。  
   **禁止**调用 `aggregate_l2` / `aggregate_members` 写 L2（会带回 tag-any）。L1 生产写路径见 Spec B（不再以「`aggregate_l1` 保持现状」为本文件真源）。  
   **禁止**把 L2 snap 的 `event_records` 送进 `append_signal_events`。  
   **禁止**把 `L2.370100` 这类假代码写入 `bars.db`。

8. **`S_temp` / `RS`：** 本 slice **保持 NULL**（与个股 RS stub 一致；不把旧的加权平均 `S_temp` 冒充同引擎）。

---

## 4. 表结构

`daily_l2` 必须增加下表两列，并写入 **`DAILY_BASKET_ALTER_COLUMNS` + `DAILY_BASKET_COLS`（及 SCHEMA）**——`upsert_daily_l2` 只持久化 `DAILY_BASKET_COLS` 内键，漏列会静默丢。`daily_l1` 列物理形态可与 L2 共享；**L1 引擎语义与个数/金额填写**以 Spec B 为准（本句原「禁止给 L1 填个数/金额冒充同引擎」仅约束 §0 当时范围，**已被 Spec B 取代**）。

| 列 | 类型 | 含义 |
|----|------|------|
| `warm_to_hot_member_count` | INTEGER | 成分温转热个数；无成分截面时 0 |
| `amount` | REAL | 成分额之和（元）；全缺则 NULL |

语义变更（无新列）：`T`、`right_side`、`tag_warm_to_hot`、`tag_warm_to_flat`、`solar_term` 改为同引擎 FSM，不再来自多数票 / tag-any / 最重成分节气。引擎整型字段在「跳过日」写 SQL NULL 时，**不得**经 `_sql_int_bool`。`warm_to_hot_member_count` 是个数，**不得**加入 `_INT_BOOL_COLS`（避免被当成 0/1）。

`signal_event`：**不**为 L2 写入 `ENTER_RIGHT` / `WARM_TO_HOT` / `EXIT_RIGHT`。开仓仍只认个股 `ENTER_RIGHT`。

`stock_sw_l2.yaml` 成员行：

```yaml
- {ts_code: 300016.SZ, sw_l2_code: '370100', name_zh: 康拓医疗}
```

`name_zh` 可缺。`map_version` 仍为 `sw2021-v1`（只加展示字段，不改归属）。

---

## 5. Issue 表头（钉死）

本 slice **覆盖** ops §5.2 中 L1 Issue / Radar 相关表头（父文档仍写「名称=代码、成交额为元」的旧样例）。

亿元列表头写 **`成交额(亿)`**。渲染时 **只**把成交额列格式化为 `amount/1e8` 的 `%.3f`（NULL→空）；**不要**改全局 `_fmt_cell` 的 `%.4g` 去动 RS 等其它数。

**行业（L2）扫描**

```text
| T | 代码 | 名称 | RS | 右侧 | 节气 | 温转热 | 成分温转热 | 成交额(亿) |
```

- `代码` = `daily_l2.code`（6 位申万二级）
- `名称` = YAML `name_zh`（可空）
- `温转热` = `daily_l2.tag_warm_to_hot`（0/1，行业自身）
- `成分温转热` = `warm_to_hot_member_count`
- 排序仍：`rank(T)` 降序，其次 `S_temp`（现多为 NULL 则只按 T）

**今日温转热（个股）**、**右侧存续 Top**、**Radar「全市场温转热 Top」**

```text
| ts_code | 名称 | …原列… | 成交额(亿) |
```

`ts_code` 仍是 `300016.SZ`；`名称` 新列。  
**今日温转平 / 结束右侧：** `| ts_code | 名称 | event | T | detail |`

Radar「按 L1」表头：本 slice 当时不变；**已被 Spec B 改为「个股温转热」+ 脚注**（见 [`2026-10-07-l1-same-engine-design.md`](2026-10-07-l1-same-engine-design.md) §5.2）。

---

## 6. 错误处理

| 情况 | 行为 |
|------|------|
| 成分全日无收益 / 停牌导致 \(R_t=\emptyset\) | 跳过该日合成 bar；引擎字段 NULL；计数/金额仍可按截面 |
| 缺 high/low | 该日 H=L=P |
| YAML 无中文名 | 名称列空 |
| 东财拉名失败 | 该票不写 `name_zh`，不失败整个 dump |
| 合成夹紧失败 | 该日当跳过 bar |
| L1 引擎 | 本 slice 历史不改；现真源见 Spec B [`2026-10-07-l1-same-engine-design.md`](2026-10-07-l1-same-engine-design.md)；Radar 不得称 L1 同引擎 |

---

## 7. 测试（Done when 的可测子集）

1. `test_C5_same_engine_on_synthetic`：两只完全相同的人造 OHLC、等权组成一 L2 → L2 的 `T`/`right_side`/`tag_warm_to_hot`/`solar_term` 与单只 `replay_from_ohlc` 在 asof 一致。
2. 多数票凉 + 一只成分 tag=1 → `daily_l2.tag_warm_to_hot=0` 且 `warm_to_hot_member_count=1`。
3. 合成收益公式夹具：两只已知收益与市值 → \(P_t\) 与手算链式指数一致（允许 1e-9 相对误差）。
4. 跳过日：asof 的 \(R_t=\emptyset\) → 引擎字段 SQL NULL（不是 0），且仍有 `warm_to_hot_member_count`/`amount`（可来自有截面的成分）。
5. digest：L2 表含「代码」「名称」「成分温转热」「成交额(亿)」；`370100` 旁为「化学制药」；个股 `ts_code` 保留、名称另列；`1.065e9` 元 → `10.650`；amount NULL → 空单元格。
6. `load_stock_sw_l2` 透传 `name_zh`；缺字段不崩；YAML 抽样含名。
7. **不要求** L1 C5、RS、9.30 `run_meta=ok`。

---

## 8. 非目标

- 不把合成 K 线写入 `bars.db` / git
- 不改 `evaluate_ok` / limit 门禁
- 不更新 14 个 L1 的引擎含义（**历史**：§0 当时；L1 现由 Spec B 定义）
- 不把「成分温转热」做成流通市值占比列（只要个数）

---

## 9. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-06 | §0 落地 |
| 2026-10-07 | Spec B CR：密度/`amount` 真源改为 YAML 成员集；L1 interim/禁填句改为指向 Spec B |
| 2026-10-07 | Spec B 实现 CR：§5 Radar 表头句改指 Spec B「个股温转热」 |
