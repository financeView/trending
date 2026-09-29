# 趋势指标引擎设计

> 状态：修订稿（已吸收 2026-09-29 subagent review）  
> 日期：2026-09-29  
> 定位：**自建同构指标体系**，非趋势动物闭源公式复刻  
> 依赖：[`2026-09-28-industry-taxonomy-design.md`](./2026-09-28-industry-taxonomy-design.md)（宇宙、L1/L2 成员闭包、tradable 集合）

## 0. 诚实边界

1. 公开语料只给出**语义与状态机**，未给出温度/节气/止盈的闭式公式。  
2. 本 spec 定义一套**可实现、可回测、可外校准**的引擎；与趋势动物像素级一致**不是**验收目标。  
3. 若持有其 API，可用截面档位一致率做**外校准**，不作为「算法正确」证明。  
4. §15 参数表为初值，允许按资产域分开校准；切点/阈值变更须走 walk-forward 或留出年，并 bump `param_version`；禁止用全样本故事拟合当真理。  
5. 金标向量与参数 YAML 须进仓库；禁止「以未提交代码夹具为准」作为规范逃避。

## 1. 目标

为 A 股（MVP）日频趋势扫描提供：

| 输出 | 用途 |
|------|------|
| 七档温度 \(T\)（主）+ 可选连续分 \(S_{temp}\) | 择时 / 节奏；列表默认按 \(T\) 序，同档内再按 \(S\) |
| 相对强度 0–100 | 选筹 / 置换 |
| 右侧状态 + 天数 | 生命周期 |
| 节气（仅右侧） | 右侧前/后段偏好，**非**进场开关 |
| 止盈辅助标签 | 默认关闭；分仓 / 应急 |

非目标：预测下一节气、复刻黑盒、多标签主题情绪、盘中分钟级温度。

## 2. 架构分层

```text
价量日线（交易日收盘）
    │
    ├─► 特征层（绝对特征 vs 相对特征隔离）
    │
    ├─► 温度引擎 ──► T_raw → 滞回 → T ──► 右侧 FSM（仅交易日切换）
    │                      └─► S_temp（可选，桶内排序）
    │                                    └─► 节气
    ├─► 强度引擎 ──► RS（按实体类 peer 宇宙分位）
    │
    └─► 止盈标签（feature flag，默认关）
```

### 2.1 硬约束

| ID | 约束 | 对应测试（§14.1） |
|----|------|-------------------|
| C1 | 温度特征只用自身绝对量；禁止截面 rank/percentile | `test_C1_temp_feature_allowlist` |
| C2 | 进右侧只由 \(T\) 驱动；RS 永不单独触发 | `test_C2_high_RS_cool_no_entry` |
| C3 | 节气不得作为强制开仓门控 | `test_C3_reject_solar_entry_gate` |
| C4 | 状态切换用交易日收盘 \(T\)；`right_side_days_natural` 仅自然日累加；字段分离 | `test_C4_calendar_split` |
| C5 | 个股/L2/L1 共用同一纯函数；合成口径见 §10；RS peer 见 §9.2 | `test_C5_same_engine_on_synthetic` |
| C6 | 统计**滞回后** \(T\) 的年化切换次数；超阈则 CI 失败（MVP 不自动改参） | `test_C6_transition_rate_cap` |

## 3. 数据输入

### 3.1 标的日线（必需）

- `ts_code`, `trade_date`, `open/high/low/close`, `amount`  
- 停牌标记、ST 标记、流通市值（合成用；缺失则该成分当日等权）  
- 价格口径：`price_adjust=qfq`（前复权），全市场统一  

### 3.2 宇宙与资格

与分类树对齐（MVP）：

| 集合 | 定义 |
|------|------|
| 分类宇宙 | 沪深 A（主板/创业板/科创板），不含北交所 |
| `members_tradable` | 宇宙内 ∧ 非 quarantine ∧ 非 ST/\*ST ∧ 非停牌 |
| 指标可算 | `members_tradable` ∧ 历史长度足够（§3.3） |

**个股 RS 资格 = 指标可算**（与 `members_tradable` + 历史门禁对齐）。不再使用「仅 in_universe∧¬quarantine」的宽松集。

页面/收藏夹分位：另传 `universe_id`，算法相同，成员由调用方提供。

### 3.3 历史长度

| 用途 | 最少交易日 |
|------|------------|
| RS | 252 |
| 温度 | `max(ma_slow + slope_n, adx_len*2, vol_hist)` → 初值按参数计为 **252** |
| ATR（节气） | `atr_len`（14） |

不足：`T=null`，`S_temp=null`，`RS=null`；不驱动右侧；不进任何 RS peer 集。

## 4. 特征层（隔离）

\(P_t\)：前复权收盘价。

### 4.1 温度专用（绝对）— MVP allowlist

仅允许下列符号进入温度决策树与 \(S_{temp}\)：

| 符号 | 定义 |
|------|------|
| \(MA_f\) | SMA(`ma_fast`) |
| \(MA_s\) | SMA(`ma_slow`) |
| \(slope_f\) | \(\ln MA_f(t) - \ln MA_f(t-slope_n)\) |
| \(slope_s\) | 对 \(MA_s\) 同上 |
| \(ADX\) | Wilder ADX(`adx_len`) |
| \(+DI,-DI\) | 同窗 |
| \(sign\) | \(\mathrm{sgn}(+DI--DI)\)，零则 0 |
| \(\sigma_n\) | 近 `vol_lookback` 日对数收益标准差 |
| \(\sigma\%ile\) | \(\sigma_n\) 在自身过去 `vol_hist` 交易日的经验分位 ∈[0,1] |
| \(ret_k\) | \(P_t/P_{t-ret_k}-1\) |
| \(ret\%ile\) | \(ret_k\) 在自身过去 `vol_hist` 日的经验分位 ∈[0,1] |

**MVP 删除 ER**（未接入决策树）。  
**禁止**：任何跨标的 rank / 截面 percentile / ROC 宇宙排名。

### 4.2 强度专用（相对）

| 符号 | 定义 |
|------|------|
| \(ROC_n\) | \(P_t/P_{t-n}-1\) |
| \(RS_{raw}\) | `rs_w1*ROC_63 + rs_w2*ROC_126 + rs_w3*ROC_189 + rs_w4*ROC_252` |

量价混合 RS 标为 **v1.1**，开启时须通过「凉/寒 + RS≥80」回归。

## 5. 温度引擎

### 5.1 布尔谓词（确定性）

```text
stack_bull   := P > MA_f AND MA_f > MA_s
stack_bear   := P < MA_f AND MA_f < MA_s
slope_up     := slope_f >  slope_eps
slope_down   := slope_f < -slope_eps
slope_flat   := |slope_f| ≤ slope_eps
di_bull      := sign ≥ 0
di_bear      := sign ≤ 0

hot_body     := stack_bull AND slope_up AND ADX ≥ adx_hot AND di_bull
warm_body    := (NOT hot_body) AND di_bull AND (
                  slope_up
                  OR (P > MA_f AND ADX ≥ adx_warm)
                )
cold_body    := stack_bear AND slope_down AND ADX ≥ adx_hot AND di_bear
cool_body    := (NOT cold_body) AND di_bear AND (
                  slope_down
                  OR (P < MA_f AND ADX ≥ adx_warm)
                )

boil_boost   := (σ%ile ≥ vol_boil) OR (ret%ile ≥ ret_boil_pctile)
freeze_boost := (σ%ile ≥ vol_freeze) OR (ret%ile ≤ ret_freeze_pctile)

flat_body    := (ADX < adx_flat) OR slope_flat
```

### 5.2 决策树 \(T_{raw}\)（全序，唯一命中）

按**自上而下第一条命中**赋值；保证互斥：

```text
if hot_body AND boil_boost:     T_raw = 沸
elif hot_body:                  T_raw = 热
elif warm_body:                 T_raw = 温
elif cold_body AND freeze_boost: T_raw = 冻
elif cold_body:                 T_raw = 寒
elif cool_body:                 T_raw = 凉
elif flat_body:                 T_raw = 平
else:                           T_raw = 平    # 强制兜底，禁止 null（历史不足除外）
```

说明：先判多头链（沸/热/温），再判空头链（冻/寒/凉），再平；兜底为平。  
金标：仓库 `fixtures/temp_raw_gold.csv`（≥20 行：特征快照 → 期望 `T_raw`），CI 必跑。

有序编码（用于 `max_step`）：

```text
rank(沸)=3, 热=2, 温=1, 平=0, 凉=-1, 寒=-2, 冻=-3
```

### 5.3 滞回与 `max_step` → 输出 \(T\)

状态：`T_prev`（上一日滞回后档）、`pending_target`、`pending_count`。

每个**交易日收盘**，在算完 `T_raw` 后：

```text
desired = T_raw
delta = rank(desired) - rank(T_prev)
# 限制单日跨越（热→沸、寒→冻 允许 |delta|=1 的极端档，不受 max_step 卡成无法进入）：
if desired in {沸,冻} and T_prev in {热,寒} and sign matches:
    stepped = desired
else:
    stepped = move rank(T_prev) toward rank(desired) by at most max_step
    # 即 stepped 的 rank = T_prev.rank + clip(delta, -max_step, +max_step)

if stepped == T_prev:
    pending_target = null; pending_count = 0
    T = T_prev
else:
    need = hysteresis_up if rank(stepped) > rank(T_prev) else hysteresis_down
    if pending_target == stepped:
        pending_count += 1
    else:
        pending_target = stepped; pending_count = 1
    if pending_count >= need:
        T = stepped; pending_target = null; pending_count = 0
    else:
        T = T_prev
```

- 计数只在**交易日**递增。  
- 「首次达热」= 滞回后 \(T\) 首次进入 `{热,沸}`。  
- `temp_transitions`（C6）只统计 `T`（滞回后）日与日变化次数。

### 5.4 连续分 \(S_{temp}\)（MVP 保留，从属）

用途：**同档 \(T\) 内排序**；列表主序必须是 \(T\) 的 rank。

```text
dir = clip( (slope_f + slope_s) / (2*slope_scale), -1, 1 )
pos = clip( (P/MA_s - 1) / band, -1, 1 )
str = clip( (ADX - adx_s_floor) / adx_s_span, 0, 1 )

bullish = max(0, dir) * str * max(0, pos) * (sign >= 0)
bearish = max(0,-dir) * str * max(0,-pos) * (sign <= 0)
S0 = 50 + 45 * (bullish - bearish)

sign_trend = 1 if rank(T_raw) > 0 else (-1 if rank(T_raw) < 0 else 0)
S_temp = clip(S0 + s_vol_weight * (σ%ile - 0.5) * sign_trend, 0, 100)
```

**序约束（CI）**：在金标+抽样实盘日上，`Spearman(rank(T), S_temp) ≥ spearman_min`（初值 0.55）；同档内不强制。若持续失败：降 `s_vol_weight` 或暂时关闭 UI 对 \(S\) 的暴露，**不得**改用 \(S\) 切档替代决策树。

### 5.5 未知态

历史不足：`T=null`，`S_temp=null`；滞回状态不推进；右侧不因 null 新开仓；若已在右侧且当日无有效 \(T\)，**沿用上一交易日 \(T\)** 做 FSM（与假期规则一致）。

## 6. 右侧状态机

### 6.1 评价时点

- **状态转移**（进入/结束右侧、温转热/温转平标签）：仅在**交易日收盘**、使用当日滞回后 \(T\)。  
- **自然日累加**：每个自然日日终，若 `R=true` 且当日未触发结束，则 `right_side_days_natural += 1`（含周末/节假日）。  
- 非交易日**不**根据「幻影 T」新开右侧。

### 6.2 伪代码

```text
# 交易日收盘：
T_today = T  # 滞回后；若 null 则 T_today = T_last_valid
tag_warm_to_hot = false
tag_warm_to_flat = false

if not R:
  if T_today in {热, 沸}:
    R = true
    right_side_days_natural = 0
    right_side_days_trading = 0
    P0 = P_t
    atr_pct_entry = ATR(atr_len)_t / P_t   # 冻结入口尺度，见 §8
    tag_warm_to_hot = true
    emit 进入右侧
else:
  if T_today in {平, 凉, 寒, 冻}:
    R = false
    tag_warm_to_flat = true
    solar_term = 立秋
    right_side_days_natural = 0
    right_side_days_trading = 0
    emit 温转平
  else:
    right_side_days_trading += 1
    if T_prev_valid == 温 and T_today in {热, 沸}:
      tag_warm_to_hot = true   # 不重置天数
    # 节气按 §8 更新

# 每个自然日日终（含非交易日）：
if R and not just_exited_today:
  right_side_days_natural += 1
```

进入日：`days_trading=0`，`days_natural` 自进入日自然日终开始累加（进入当日自然日终 +1）。夹具须覆盖：**周五进 → 周一** 的两字段期望值。

FSM 单测夹具（至少）：

1. 平→（连续 `hysteresis_up` 日热）→ 进入；不足滞回日不进入  
2. 热→温 存续，天数增加  
3. 温→平 结束，天数清零  
4. 右侧内温→热：标签真，天数不重置  
5. 周五确认热、周末自然日 +2、周一仍在右侧  

## 7. \(S\) / \(T\) 产品规则（固化）

| 场景 | 规则 |
|------|------|
| 列表主排序「按温度」 | 先 `rank(T)` 降序，再 `S_temp` 降序 |
| 档位展示 | 只展示 \(T\) |
| 决策 / FSM | 只用 \(T\) |
| MVP 可否去掉 \(S\) | 可；若去掉，本 § 与 §5.4 整段标 deprecated，输出字段可空 |

## 8. 节气（仅 `right_side=true`）

### 8.1 语义

| 节气 | 含义 |
|------|------|
| 谷雨 | 蛰伏 / 噪声内 |
| 立夏 | 萌芽 |
| 夏至 | 发展 |
| 小暑 | 破圈加速 |
| 大暑 | 后段拥挤 |
| 立秋 | 结束当日 |

### 8.2 因果进度（无前视）

入口冻结：`P0`、`atr_pct_entry = ATR(atr_len)/P`（进入日）。  
进行中：

```text
g_raw = ln(P_t / P0) / max(atr_pct_entry, atr_floor)
d_raw = right_side_days_trading / stage_D0
v_raw = σ%ile                         # 当日，允许波动推高阶段

g = piecewise_linear(g_raw, knots_g)  # → [0,1]
d = piecewise_linear(d_raw, knots_d)
v = piecewise_linear(v_raw, knots_v)

stage_score = w_g*g + w_d*d + w_v*v
```

**初值 knots（写入参数表）**

| 输入 | 结点 (x → y) |
|------|----------------|
| `knots_g` | (0→0), (0.5→0.25), (1.5→0.55), (3.0→0.8), (5.0→1.0) |
| `knots_d` | (0→0), (0.25→0.3), (0.5→0.55), (1.0→0.85), (1.5→1.0) |
| `knots_v` | (0→0), (0.5→0.2), (0.75→0.5), (0.9→0.8), (1.0→1.0) |

切段：

| stage_score | 节气 |
|-------------|------|
| < 0.15 | 谷雨 |
| < 0.35 | 立夏 |
| < 0.55 | 夏至 |
| < 0.75 | 小暑 |
| ≥ 0.75 | 大暑 |

校准：只允许 walk-forward / 留出年改 knots 或切点；全样本拟合禁止。变更 → 新 `param_version`。

### 8.3 MVP 不做

下行节气；时长分布时间桶；节气预测；`require_solar_term_for_entry` 类配置（实现层应拒绝）。

## 9. 相对强度引擎

### 9.1 计算

```text
RS_raw = rs_w1*ROC63 + rs_w2*ROC126 + rs_w3*ROC189 + rs_w4*ROC252
RS = round(100 * percentile_rank(RS_raw among peer_universe))  # 0–100 整数
```

`percentile_rank`：平均秩，同分同值；peer 为空或仅 1 人 → `RS=null`。

### 9.2 Peer 宇宙（按实体类）

| 实体 | `universe_id` | peer 集 |
|------|---------------|---------|
| 个股 | `local_stock` | 当日「指标可算」个股 |
| L2 合成 | `local_l2` | 当日有有效合成价且温度可算的全部 L2 |
| L1 合成 | `local_l1` | 当日可算的全部 L1 |
| 调用方池 | `custom:<id>` | 调用方传入的可算成员 |

战场雷达与选筹必须带上所用 `universe_id`。

### 9.3 共线回归

固定夹具或合成截面：至少一例 **\(T\in\{凉,寒\}\) 且 RS≥80`**。系统性做不到则失败，回查温度是否偷用相对动量。

## 10. 聚合：L2 / L1

1. 成分集：默认分类树 `members_tradable`；配置项 `member_set=tradable|total`。  
2. 合成：成分日收益按流通市值加权（缺失市值则当日该缺失成分退出加权，或全体等权——**MVP：缺失市值则等权**），链式指数。  
3. 对合成序列调用与个股相同的温度/RS/右侧/节气纯函数。  
4. L1：**成员闭包一次合成**（不先 L2 再嵌套）。  
5. 输出必须带 `map_version`、`member_set`、`universe_id`、`param_version`。

雷达：`radar_level=stock|l2`；统计温转热个数、右侧占比。

## 11. 止盈辅助标签（默认关闭）

| 标签 | 定义（flag 打开后才生效） | 稀疏度 |
|------|---------------------------|--------|
| 波动率放大 | `R` 且节气∈{小暑,大暑} 且 \(\sigma\%ile ≥ vol_expand_pctile` | 全市场日标签率 < `tag_rate_cap` |
| 开香槟 | 连续 `champ_k` 个交易日：日收益 > 同日 `local_stock` 宇宙收益中位数，且窗口累计超额 ≥ `champ_excess` | 同上 |
| 危险信号 | 日收益分位 ≤ `danger_ret_pctile` 且成交额分位 ≥ `danger_amt_pctile`（自身 `vol_hist` 窗） | 同上 |

`tag_rate_cap` 初值 0.02（标的·日）。未达定义前保持 flag 关。

## 12. 输出契约

```text
as_of_date                  # 交易日
entity_type                 # stock | l2 | l1
ts_code | sw_l2_code | l1_id
map_version
member_set                  # tradable | total
param_version
universe_id                 # local_stock | local_l2 | local_l1 | custom:*

T                           # 七档 | null
S_temp                      # 0–100 | null
RS                          # 0–100 | null

right_side
right_side_days_natural
right_side_days_trading
tag_warm_to_hot
tag_warm_to_flat
solar_term                  # 谷雨…大暑 | 立秋 | null
tags[]                      # 若 flag 关则为 []

filters_meta                # 复权、资格过滤摘要
```

## 13. 参数表（初值，须尽数列出）

| 键 | 初值 | 说明 |
|----|------|------|
| `price_adjust` | qfq | |
| `ma_fast` | 20 | |
| `ma_slow` | 60 | |
| `slope_n` | 5 | |
| `slope_eps` | 0.001 | \(\ln MA\) 差阈值 |
| `slope_scale` | 0.02 | \(S\) 用 |
| `band` | 0.15 | \(S\) 用 |
| `adx_len` | 14 | |
| `adx_hot` | 25 | |
| `adx_warm` | 18 | |
| `adx_flat` | 20 | |
| `adx_s_floor` | 15 | \(S\) |
| `adx_s_span` | 25 | \(S\) |
| `vol_lookback` | 20 | |
| `vol_hist` | 252 | |
| `vol_boil` | 0.90 | |
| `vol_freeze` | 0.90 | |
| `ret_k` | 10 | |
| `ret_boil_pctile` | 0.95 | |
| `ret_freeze_pctile` | 0.05 | |
| `hysteresis_up` | 2 | 交易日 |
| `hysteresis_down` | 1 | |
| `max_step` | 2 | rank 步长 |
| `s_vol_weight` | 5 | |
| `spearman_min` | 0.55 | T vs S |
| `temp_transition_cap_per_year` | 80 | C6，滞回后 |
| `rs_w1..w4` | 0.4,0.2,0.2,0.2 | |
| `atr_len` | 14 | |
| `atr_floor` | 0.01 | |
| `stage_D0` | 60 | |
| `w_g,w_d,w_v` | 0.55,0.25,0.20 | |
| `knots_g/d/v` | 见 §8.2 | |
| `stage_cuts` | 0.15,0.35,0.55,0.75 | |
| `vol_expand_pctile` | 0.90 | flag |
| `champ_k` | 3 | flag |
| `champ_excess` | 0.05 | flag |
| `danger_ret_pctile` | 0.05 | flag |
| `danger_amt_pctile` | 0.95 | flag |
| `tag_rate_cap` | 0.02 | flag |
| `exit_tags_enabled` | false | |

配置文件：`config/metrics/a_share_daily.yaml` + `fixtures/temp_raw_gold.csv`。

## 14. 验收

### 14.1 硬约束测试映射

| 测试名 | 断言要点 |
|--------|----------|
| `test_C1_temp_feature_allowlist` | 温度路径 AST/特征字典 ⊆ §4.1；无截面 rank |
| `test_C2_high_RS_cool_no_entry` | 强制 RS=99 且 \(T=凉\) → `R` 保持 false |
| `test_C3_reject_solar_entry_gate` | 策略配置若要求节气才开仓 → 校验器拒绝 |
| `test_C4_calendar_split` | 周五进、跨周末：`days_trading` 与 `days_natural` 符合 §6 夹具 |
| `test_C5_same_engine_on_synthetic` | 人造价序列个股函数 vs 标为 l2 调用结果一致；peer 为 `local_l2` |
| `test_C6_transition_rate_cap` | 夹具序列年化 `temp_transitions` ≥80 → 失败（或标参不合格） |
| `test_temp_raw_gold` | ≥20 向量决策树命中 |
| `test_hysteresis_max_step` | 计数/封顶行为符合 §5.3 |
| `test_RS_peer_universes` | 三类 `universe_id` 隔离 |
| `test_RS_eligibility_tradable` | ST/停牌不进 `local_stock` peer |
| `test_colinearity_story` | 凉/寒 + RS≥80 存在 |
| `test_T_S_spearman` | ≥ `spearman_min` |

### 14.2 FSM / 其它

- 滞回不足不进入右侧；热→温存续；温→平结束；温→热不重置天数。  
- 历史不足 → null。  
- 主策略回测路径不得依赖节气门控。

### 14.3 可选外校准

外部 API 档位一致率：监控仪表，默认不设硬阈。

## 15. 已知漏洞与 backlog

| ID | 问题 | 方向 |
|----|------|------|
| V1 | 阈值非官方真值 | 外校准 + 域搜索 |
| V2 | \(S\) 粗糙 | 学权重或 MVP 隐藏 |
| V3 | 节气事后标签 | 保持 C3 |
| V4 | 市值 vs 等权 | A/B 雷达 |
| V5 | 自然日假期膨胀 | UI 双展示；节气用交易日 |
| V6 | 止盈过拟合 | 默认关 + 稀疏度 |
| V7 | 多资产 | 分域参数 |
| V8 | 自动加大滞回 | v1.1 策略，非 MVP |

## 16. 实现顺序

1. 特征 allowlist + `T_raw` 金标  
2. 滞回 / max_step → \(T\)  
3. RS + 三类 peer + tradable 资格  
4. 右侧 FSM（交易日切换 + 自然日计数夹具）  
5. \(S_{temp}\) + Spearman 门禁  
6. L2/L1 合成 + 同引擎  
7. 节气  
8. 止盈 flag（默关）  

实现计划：`docs/superpowers/plans/`（本修订稿确认后）。

## 17. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-09-29 | 初版落盘 |
| 2026-09-29 | review 修订：确定性 T 树+金标；S 从属序约束；RS peer；tradable 对齐；FSM 日历；C1–C6 测试映射；参数表补全；修交叉引用；节气 knots/ATR 入口冻结 |
