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

- `percentile_rank`：平均秩，同分同值；peer 空或仅 1 人 → `RS=null`。  
- `ROC_n = P_t/P_{t-n}-1`（前复权收盘）；任一腿因历史不足不可算 → 该实体当日 `RS_raw=null`，**不进** peer。  
- 默认权重：`rs_w1..w4 = 0.4, 0.2, 0.2, 0.2`（入 `config/metrics/a_share_daily.yaml`）。

| 实体 | `universe_id` | peer 集 |
|------|---------------|---------|
| 个股 | `local_stock` | 当日指标可算 ∧ `RS_raw≠null`；ST/停牌不进 |
| L2 | `local_l2` | 当日合成可算 ∧ `RS_raw≠null` |
| L1 | `local_l1` | 同上 |

**指标可算** = `members_tradable` 资格 ∧ 历史长度足够（RS 腿需 252，与 metrics §3.2–3.3 对齐）。不采用「有 bar 即可」的宽松集。

### 2.2 `S_temp` 与 C1

- 公式真源 = metrics §5.4；特征 ⊆ §4.1 **绝对量**；禁止截面 rank / 宇宙 ROC 进入温度或 `S_temp` 路径。  
- 用途：同档 \(T\) 内排序；**不得**替代决策树切档或单独触发右侧（C2 逻辑本 slice 不改代码路径，仅靠 C1 + 现有 FSM 保持）。  
- CI：`Spearman(rank(T), S_temp) ≥ spearman_min`（0.55）于**金标+合成夹具**；实盘抽样日 Spearman **后放**。

### 2.3 旁路 `VOL_score`（个股必做；篮子后放）

**个股**

```text
turnover_t = amount_t / float_mv_t   # 两者皆有限且 float_mv>0；否则当日 turnover=null
VOL_score  = round(100 * percentile_rank(turnover_t among own history))  # 0–100
```

- 自身历史窗：与 `vol_hist` 对齐（252 交易日，仅计 `turnover` 非 null 的样本）；样本不足（spec 钉：**少于 60** 有效日）→ `VOL_score=null`。  
- `percentile_rank` 同 RS：平均秩；仅 1 个有效样本 → null。  
- **不**排除涨停日（本 slice 不加特殊规则；后放可加）。

**L2 / L1（本 slice）**

- 列存在，写入值 **恒 SQL NULL**。  
- **原因（须在实现/digest 脚注可追溯）：** 非 null 篮子量分需要按日攒 Σamount/Σfloat_mv 历史序列再自身分位，成本与已后放的 L2/L1 全历史 replay / `engine_state` 同型；本 slice 优先闭合价格 RS + 个股量旁路，避免再开一条篮子时序工程。后续可单开补丁把篮子量分做成与个股同型（Σamount/Σmv → 自身分位）。  
- digest 篮子行「量」列空；排序在 `VOL_score` 全 null 时自然退化为 `RS → amount`。

### 2.4 明确不做

- 量进 `RS`（线性 mix / 乘法 boost / 改名冒充实 RS）  
- 用 `aggregate_*` 加权平均成员 `RS`/`S_temp` 冒充同引擎  
- 实盘日 Spearman 硬门、C2 新测、全 A peer、YAML 日拉  
- L2/L1 非 null `VOL_score`

---

## 3. 数据流

```text
bars / 合成 OHLC
  → per-entity replay_from_ohlc
       §4.1 特征 → T / 滞回 / FSM / 节气（行为不变）
       + S_temp（§5.4）
       + RS_raw（ROC 加权；写入 snap，供截面）
       + 个股：日 turnover（供 VOL 自身分位）
  → asof 截面 pass（实体类隔离）
       peer 分位 → RS
       个股 own-history → VOL_score
       L2/L1 VOL_score := null
  → upsert daily_* + universe_id + param_version
  → signal_event.RS := 当日该股 RS（可算则写）
  → digest
```

实现约束：

1. 截面 pass **只**写 `RS`（及个股 `VOL_score`）；不得回写 `T` / 右侧 / 节气。  
2. `replay_from_ohlc` 保持无全局 peer 缓存；禁止 Approach 2 式「replay 内查截面」。  
3. 生产路径继续禁止 `aggregate_l1` / `aggregate_members` 写引擎列（Spec B 已钉）。

---

## 4. 落库 / 参数 / digest

### 4.1 Schema

经 `ensure_column` / ALTER 列表：

| 表 | 变更 |
|----|------|
| `daily_stock` | `VOL_score REAL`；`S_temp`/`RS` 真值；`universe_id='local_stock'`；`param_version` 列若缺则加并写入 |
| `daily_l2` | `VOL_score REAL`（恒 null）；`S_temp`/`RS` 真值；`universe_id='local_l2'`；`param_version` |
| `daily_l1` | 同 L2，`universe_id='local_l1'` |
| `signal_event` | `RS` 与当日个股一致（可算时）；无 `VOL_score` 列 |

空值：SQL NULL → digest **空单元格**（禁止渲染 `0`）。

### 4.2 参数

`config/metrics/a_share_daily.yaml` / `MetricsParams`：

- 新增 `rs_w1..rs_w4`（默认 0.4 / 0.2 / 0.2 / 0.2）  
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

---

## 5. 测试与 Done when

### 5.1 必测

| 测试 | 断言 |
|------|------|
| `test_C1_temp_feature_allowlist` | 温度/`S_temp` 特征 ⊆ §4.1；无截面 rank |
| `test_RS_peer_universes` | 三类 `universe_id` 分位隔离 |
| `test_RS_eligibility_tradable` | ST/停牌 ∉ `local_stock` peer |
| `test_colinearity_story` | ∃ 凉/寒 且 RS≥80（合成或金标） |
| `test_T_S_spearman` | 金标+合成 Spearman ≥ `spearman_min`；不含实盘日 |
| `test_VOL_score_stock` | 个股公式与 null 规则；L2/L1 写入后仍 null |
| `test_digest_rs_vol_sort` | 表头含「量」；排序键；NULL→空 |

### 5.2 Done when

1. 可算个股/L2/L1 asof：`RS` ∈ {0..100 整数} 或合法 null；`universe_id` / `param_version=p05-v2` 正确。  
2. 可算个股：`S_temp`∈[0,100] 或 null；`VOL_score` 同规。  
3. L2/L1：`VOL_score` 恒 null。  
4. `signal_event.RS` 与当日个股一致（可算时）。  
5. digest 右侧 Top 按真 RS（+量+额）；全民 null RS 的成交额冒充路径消失。  
6. §5.1 测试全绿；`todo.md` Spec C **已完成**；README Still out 去掉 RS peer / Spearman / `test_C1`。  
7. **不要求：** 9.30 实盘重跑过门、篮子非 null 量分、量混 RS、实盘 Spearman、C2 新测。

---

## 6. 实现落点（供 plan）

| 模块 | 职责 |
|------|------|
| `scripts/metrics/features.py`（或 `rs.py`） | `ROC_n` / `RS_raw`；保持与温度特征列隔离 |
| `scripts/metrics/s_temp.py`（新）或等价 | §5.4；仅用 allowlist 特征 |
| `scripts/metrics/vol_score.py`（新）或等价 | 个股 turnover 自身分位 |
| `scripts/metrics/pipeline.py` | snap 带 `S_temp`、`RS_raw`；**不**在此算截面 `RS` |
| `scripts/metrics/peer_rs.py`（新）或 `daily_run` 内 | asof 三类 peer → `RS` |
| `scripts/daily_run.py` | 去掉篮子 `S_temp`/`RS` 硬编码 null；截面后写入；事件带 RS |
| `scripts/common/db.py` | `VOL_score` / basket `universe_id` / `param_version` 列 |
| `scripts/issues/digest.py` | 「量」列 + 排序 |
| `config/metrics/a_share_daily.yaml` | `rs_w*` + `param_version: p05-v2` |
| `tests/test_*.py` | §5.1 |

建议任务切分（plan 可调）：T0 docs 权威 → T1 `RS_raw`+params → T2 `S_temp`+C1/Spearman 测 → T3 peer 截面 → T4 个股 VOL + schema → T5 digest + 事件 RS → T6 done-when 文档。

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-07 | 初版：价格 RS + S_temp/C1 + 个股 VOL 旁路；否决量混 RS；L2/L1 VOL 后放并写明原因；Approach 1 截面后处理；`param_version=p05-v2` |
