# Spec C：价格 RS + S_temp/C1 + 旁路 VOL_score

**日期：** 2026-10-07  
**状态：** 设计已钉；待 plan / 实现  
**范围：** metrics §9 价格相对强度（三类 peer）+ §5.4 `S_temp` + §14 `test_C1` / Spearman 夹具门禁 + 个股旁路量分 `VOL_score`；digest §1.3 真 RS 排序与「量」列。  
**后放（禁止混入本 slice）：** 量能线性/乘法混入 `RS`（否决的「量价混合 RS v1.1」）；L2/L1 非 null `VOL_score`（见 §2.3 原因）；实盘 asof 日 Spearman；Spec D 全 A / YAML 日拉；Spec E `board_calc` / 硬冻旗；C2 开仓夹具扩面；L2/L1 全历史 replay / `engine_state`；改温度决策树。

交叉：metrics [`2026-09-29-trend-metrics-engine-design.md`](2026-09-29-trend-metrics-engine-design.md) §4 / §5.4 / §9 / §14 · L2 [`2026-10-06-l2-same-engine-digest-design.md`](2026-10-06-l2-same-engine-digest-design.md) · L1 [`2026-10-07-l1-same-engine-design.md`](2026-10-07-l1-same-engine-design.md) · market-data [`2026-10-01-market-data-contract-design.md`](2026-10-01-market-data-contract-design.md) §6 · 待办 [`todo.md`](../../../todo.md) §1.3 / §2.2 / Spec C

产品对齐：「温度定时机，强度定选筹」——本 slice 补齐**强度**半边；量能作旁路确认/二次排序，**不**改写 RS 语义（IBD/O'Neil RS 为纯价格；调研见会话记录）。

---

## 1. 问题

- `daily_* .RS` / `S_temp` 为 stub null；`_basket_asof_row` 硬编码 NULL。  
- digest「右侧存续 Top（RS 高）」在全民 null RS 下退化为成交额榜（todo §1.3）。  
- `test_C1` / peer 隔离 / Spearman / colinearity 未做；`rs_w1..w4` 未进 yaml。  
- 曾考虑量价 mix 进 RS；与业界（价格 RS + 量独立过滤）及「凉/寒 + RS≥80」可分离性冲突 → **不做**。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 架构 | **Approach 1：截面后处理**——单标的 replay 出绝对量 + `RS_raw`；asof 再按实体类 peer 分位 → `RS` |
| RS | metrics §9.1 **纯价格** ROC 加权；`RS = round(100 * percentile_rank(RS_raw among peer))` |
| 量 | 旁路 `VOL_score`；**不**进 `RS`、**不**进温度路径 |
| `S_temp` | §5.4 同发；CI Spearman 仅金标+合成 |
| digest | 真 RS；表头加「量」；排序 `RS → VOL_score → amount` |

### 2.1 价格 RS

```text
RS_raw = rs_w1*ROC_63 + rs_w2*ROC_126 + rs_w3*ROC_189 + rs_w4*ROC_252
RS     = round(100 * percentile_rank(RS_raw among peer_universe))  # 0–100 整数
```

**`percentile_rank`（本 slice 闭合公式；RS 与 VOL_score 共用）**

对有限样本集合 \(x_1..x_n\)（\(n\ge 2\)）：

1. 平均秩：同分取名次算术平均（1-based）。  
2. \(p_i = (rank_i - 1) / (n - 1)\) ∈ [0, 1]。  
3. 对外分：`round(100 * p_i)` → 0–100 整数。  

\(n\le 1\) 或集合为空 → 该实体当日分数 **null**（不进 peer 的产出侧亦为 null）。  
（注：温度特征里的 `_empirical_pctile` / σ%ile 仍用既有「窗内 ≤ 计数 / 窗长」实现，**不**被本公式替换。）

- `ROC_n = P_t/P_{t-n}-1`（前复权收盘）；任一腿因历史不足不可算 → 该实体当日 `RS_raw=null`，**不进** peer。  
- 默认权重：`rs_w1..w4 = 0.4, 0.2, 0.2, 0.2`（入 `config/metrics/a_share_daily.yaml`）。

| 实体 | `universe_id` | peer 集 |
|------|---------------|---------|
| 个股 | `local_stock` | 当日 ∈ `members_tradable`（宇宙内 ∧ ¬quarantine ∧ ¬ST ∧ ¬停牌）∧ 历史足够 ∧ `RS_raw≠null` |
| L2 | `local_l2` | 当日有有效合成价 ∧ **温度可算**（asof 引擎 `T` 非 null）∧ `RS_raw≠null` |
| L1 | `local_l1` | 同上 |

跳过日 / 无合成 bar / asof 引擎字段全 null 的篮子：**不进** peer。  
不采用「有 bar 即可」的宽松集。篮子侧「指标可算」**不要**误用个股表上的 `members_tradable` 计数字段当资格布尔。

**与 C5：** 同引擎断言的是合成序列上的纯函数输出（`T` / FSM / 节气 / `S_temp` / **`RS_raw`**）与孪生个股一致；截面 `RS` 依赖 `local_l2`/`local_l1` peer，**不得**要求与个股 `RS` 数值相等。既有 `test_C5_*` 保持绿；peer 行为由 `test_RS_peer_universes` 覆盖。

### 2.2 `S_temp` 与 C1

- 公式真源 = metrics §5.4；特征 ⊆ §4.1 **绝对量**；禁止**跨标的**截面 rank / 宇宙 ROC 进入温度或 `S_temp` 路径。  
- 允许：§5.4 内对 **`T_raw` 档位** 的 `rank(T_raw)`（标的自身有序编码，非截面）。  
- `test_C1` 作用域 = 温度决策树 + `S_temp` 计算图；**排除** `peer_rs` / `VOL_score` 模块。  
- 用途：同档 \(T\) 内排序；**不得**替代决策树切档或单独触发右侧（C2 逻辑本 slice 不改代码路径）。  
- CI Spearman：本 slice **临时豁免** metrics §5.4「金标+抽样实盘日」中的实盘腿——仅 **金标+合成夹具** 上 `Spearman(rank(T), S_temp) ≥ spearman_min`（0.55）。实盘抽样日 Spearman **后放**；metrics 权威文在本 slice 落地时加一句修订注指向本豁免，避免静默分叉。

### 2.3 旁路 `VOL_score`（个股必做；篮子后放）

**个股**

```text
turnover_t = amount_t / float_mv_t   # 两者皆有限且 float_mv>0；否则当日 turnover=null
VOL_score  = round(100 * percentile_rank(turnover_t among window))  # 公式同 §2.1
```

- 窗脊：**与该股 `replay_from_ohlc` 所用 OHLC 交易日序列同一条脊**（按 bar/会话日，**含当日 t**）；取脊上最近至多 `vol_hist`（252）根；**不**另开日历 pad、不插入无 bar 的空日。  
- 分位只在窗内 `turnover` 非 null 的样本上算。  
- **当日 `turnover_t` 非有限（null）→ `VOL_score=null`**，即使窗内有效样本 n ≥ `vol_score_min_samples`——禁止用「昨日分位」顶今日。  
- `n < vol_score_min_samples`（默认 **60**，入 yaml / `MetricsParams`）或 `n≤1` → `VOL_score=null`。  
- **不**排除涨停日（本 slice 不加特殊规则；后放可加）。

**L2 / L1（本 slice）**

- 列存在，写入值 **恒 SQL NULL**。  
- **原因（须在实现/digest 脚注可追溯）：** 非 null 篮子量分需要按日攒 Σamount/Σfloat_mv 历史序列再自身分位，成本与已后放的 L2/L1 全历史 replay / `engine_state` 同型；本 slice 优先闭合价格 RS + 个股量旁路，避免再开一条篮子时序工程。后续可单开补丁把篮子量分做成与个股同型（Σamount/Σmv → 自身分位）。  
- digest 篮子行「量」列空；排序在 `VOL_score` 全 null 时自然退化为 `RS → amount`。

### 2.4 明确不做

- 量进 `RS`（线性 mix / 乘法 boost / 改名冒充实 RS）；todo §2.2「量价混合可跟」**以本条为准作废**，改为旁路 `VOL_score`  
- 用 `aggregate_*` 加权平均成员 `RS`/`S_temp` 冒充同引擎  
- 实盘日 Spearman 硬门、C2 新测、全 A peer、YAML 日拉  
- L2/L1 非 null `VOL_score`  
- Spec B 曾钉的篮子 `S_temp`/`RS` 恒 NULL：**被本 slice 取代**（改为同引擎真值 + 截面 `RS`）

---

## 3. 数据流

```text
bars / 合成 OHLC
  → per-entity replay_from_ohlc
       §4.1 特征 → T / 滞回 / FSM / 节气（行为不变）
       + S_temp（§5.4）
       + RS_raw（ROC 加权；写入 snap，供截面）
       + 个股：日 turnover（供 VOL 自身分位）
       （此时 event_records 尚无截面 RS）
  → asof 截面 pass（实体类隔离）
       peer 分位 → 派生 RS
       个股 own-history → 派生 VOL_score
       L2/L1 VOL_score := null
  → 内存回填：events[].RS := 该 ts_code 当日 RS（可算则写，否则保持 null）
  → upsert daily_*（含 S_temp / RS / VOL_score / universe_id / param_version）
  → append_signal_events（禁止事后 UPDATE signal_event）
  → digest
```

实现约束：

1. **截面 pass 只派生** `RS` 与个股 `VOL_score`；不得回写 `T` / 右侧 / 节气。`S_temp` / `universe_id` / `param_version` 在 replay 或 upsert 写入，不在 peer 循环里改 FSM。  
2. `replay_from_ohlc` 保持无全局 peer 缓存；禁止 Approach 2 式「replay 内查截面」。  
3. 生产路径继续禁止 `aggregate_l1` / `aggregate_members` 写引擎列（Spec B 已钉）。  
4. **事件时序（钉死）：** 必须先完成 asof peer → 再改内存 `events[].RS` → 再 `upsert` → 再 `append_signal_events`。禁止先以 `RS=null` insert 再 UPDATE。首次 `param_version=p05-v2` 重跑相对旧库中 active 且 `RS` null 的同行，允许因 payload 变化而 **supersede**（`append_signal_events` 既有语义）。

---

## 4. 落库 / 参数 / digest

### 4.1 Schema

经 `ensure_column` / ALTER 列表：

| 表 | 变更 |
|----|------|
| `daily_stock` | ALTER：`VOL_score REAL`、`param_version TEXT`；写入 `S_temp`/`RS`/`VOL_score` 真值；`universe_id='local_stock'`；`param_version='p05-v2'`；同步 `DAILY_STOCK_COLS` / `DAILY_STOCK_ALTER_COLUMNS` |
| `daily_l2` | ALTER：`VOL_score REAL`、`universe_id TEXT`、`param_version TEXT`；`VOL_score` 恒 null；`S_temp`/`RS` 真值；`universe_id='local_l2'`；同步 `DAILY_BASKET_COLS` / ALTER 列表 |
| `daily_l1` | 同 L2，`universe_id='local_l1'` |
| `signal_event` | 无新列；`RS` 与当日 `daily_stock` 该票一致（可算则写，不可算则 null） |
| `run_meta` | 继续写 run 级 `param_version`（已有）；行级镜像 `p05-v2`，不改 ok_predicate |

空值：SQL NULL → digest **空单元格**（禁止渲染 `0`）。  
metrics §10 的 `map_version` / `member_set` 落篮子行：**本 slice 不补**（既有债，单列 backlog，不假装 §10 输出契约已满）。

### 4.2 参数

`config/metrics/a_share_daily.yaml` / `MetricsParams`：

- 新增 `rs_w1..rs_w4`（默认 0.4 / 0.2 / 0.2 / 0.2）  
- 新增 `vol_score_min_samples: 60`  
- **`param_version`: `p05-v1` → `p05-v2`**（本 slice 钉死此字符串）  
- 已有 `spearman_min` / `s_vol_weight` / `vol_hist` 沿用

### 4.3 Digest

| 块 | 变更 |
|----|------|
| 右侧存续 Top（RS 高） | 表头加 **量**；`ORDER BY IFNULL(RS,-1e99) DESC, IFNULL(VOL_score,-1e99) DESC, IFNULL(amount,0) DESC` |
| L2 扫描 / L1 自身 / Radar 含 RS 的表 | 同样加 **量** 列；篮子量空 |
| L2/L1 主排序 | 仍 `rank(T)` 再 `S_temp`（S 有值后生效）；VOL 不抬主序 |
| 今日温转热 | 仍按成交额（本 slice 不改） |

脚注（L1/L2 表或 Radar 一处即可）：L2/L1「量」本 slice 为空——篮子 VOL 后放（避历史换手序列成本）。

**排序语义（钉死）：** 过滤集内存在 ≥1 个非 null `RS` 时，主序为 RS（§1.3 目标达成）。过滤集 `RS` 全 null 时仍会按 `VOL_score→amount` 退化——这是并列键的合法行为，**不**宣称「成交额冒充路径已从 SQL 消失」。

---

## 5. 测试与 Done when

### 5.1 必测

| 测试 | 断言 |
|------|------|
| `test_C1_temp_feature_allowlist` | 温度/`S_temp` 图 ⊆ §4.1；无**跨标的**截面 rank；允许 `rank(T_raw)`；不含 vol/peer 模块 |
| `test_RS_peer_universes` | 三类 `universe_id` 分位隔离 |
| `test_RS_eligibility_tradable` | ST/停牌/quarantine ∉ `local_stock` peer |
| `test_colinearity_story` | ∃ 凉/寒 且 RS≥80（合成或金标） |
| `test_T_S_spearman` | 金标+合成 Spearman ≥ `spearman_min`；不含实盘日（§2.2 豁免） |
| `test_VOL_score_stock` | 个股窗脊=OHLC；公式/`vol_score_min_samples`；**当日 turnover null → VOL null**；L2/L1 写入后仍 null |
| `test_digest_rs_vol_sort` | 表头含「量」；排序键；NULL→空 |
| `test_signal_event_rs_matches_daily` | 同日同票 active `signal_event.RS` 与 `daily_stock.RS` 一致；双方 null 亦一致 |

### 5.2 Done when

1. 可算个股/L2/L1 asof：`RS` ∈ {0..100 整数} 或合法 null；`universe_id` / `param_version=p05-v2` 正确。  
2. 可算个股：**且**可算 L2/L1：`S_temp`∈[0,100] 或 null；可算个股 `VOL_score` 同规。  
3. L2/L1：`VOL_score` 恒 null。  
4. `signal_event.RS` 与当日个股一致（含双 null）；见 `test_signal_event_rs_matches_daily`。  
5. digest 右侧 Top：有非 null RS 时主序为 RS（+量+额）；全 null 时允许 VOL→amount 退化（§4.3）。  
6. §5.1 测试全绿；`todo.md` Spec C **已完成**（改写为价格 RS + C1/Spearman 夹具 + 旁路 VOL；删「量价混合可跟」）；README Still out 去掉 RS peer / Spearman / `test_C1`。  
7. **T0 docs（同 slice 权威同步，防双源）：**  
   - metrics §5.4：实盘 Spearman 本 slice 豁免修订注；  
   - metrics §9.1：`percentile_rank` 对齐本文件 §2.1 闭合式；  
   - metrics §13：增列 `rs_w1..w4`、`vol_score_min_samples`（初值 60）。  
8. **不要求：** 9.30 实盘重跑过门、篮子非 null 量分、量混 RS、实盘 Spearman、C2 新测、`map_version`/`member_set` 落篮子行。

---

## 6. 实现落点（供 plan）

| 模块 | 职责 |
|------|------|
| `scripts/metrics/features.py`（或 `rs.py`） | `ROC_n` / `RS_raw`；保持与温度特征列隔离 |
| `scripts/metrics/s_temp.py`（新）或等价 | §5.4；仅用 allowlist 特征 |
| `scripts/metrics/vol_score.py`（新）或等价 | 个股 turnover 自身分位 |
| `scripts/metrics/pipeline.py` | snap 带 `S_temp`、`RS_raw`；**不**在此算截面 `RS` |
| `scripts/metrics/peer_rs.py`（新）或 `daily_run` 内 | asof 三类 peer → `RS` |
| `scripts/daily_run.py` | 去掉篮子硬编码 null；peer 后回填 `events[].RS` 再 append；upsert 行级字段 |
| `scripts/common/db.py` | `VOL_score` / basket `universe_id` / 行级 `param_version`；COLS/ALTER 齐全 |
| `scripts/issues/digest.py` | 「量」列 + 排序 |
| `config/metrics/a_share_daily.yaml` | `rs_w*` + `vol_score_min_samples` + `param_version: p05-v2` |
| metrics 权威 | T0：§5.4 Spearman 豁免注；§9.1 闭合 `percentile_rank`；§13 增 `rs_w*` / `vol_score_min_samples` |
| `tests/test_*.py` | §5.1（含：当日 turnover null → VOL null） |

建议任务切分（plan 可调）：T0 docs 权威（§5.4/§9.1/§13）→ T1 `RS_raw`+params+`percentile_rank` → T2 `S_temp`+C1/Spearman 测 → T3 peer 截面 + 事件 RS 时序 → T4 个股 VOL + schema → T5 digest → T6 done-when 文档。

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-07 | 初版：价格 RS + S_temp/C1 + 个股 VOL 旁路；否决量混 RS；L2/L1 VOL 后放并写明原因；Approach 1 截面后处理；`param_version=p05-v2` |
| 2026-10-07 | CR 真项修补：闭合 `percentile_rank`；篮子 peer=温度可算；事件时序 peer→内存 RS→append；VOL 窗含 t + `vol_score_min_samples`；Spearman 实盘豁免+metrics 注；C5=`RS_raw`；Done-when/测试补事件 RS 与排序语义；Spec B 篮子 S/RS NULL 被取代；C1 作用域 |
| 2026-10-07 | 二审真项：当日 turnover null→VOL null；VOL 窗脊=replay OHLC；T0 同步 metrics §9.1/§13/`vol_score_min_samples` |
