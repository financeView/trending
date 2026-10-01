# 趋势指标引擎设计

> 状态：修订稿（已吸收 2026-09-29 subagent review）  
> 日期：2026-09-29  
> 定位：**自建同构指标体系**，非趋势动物闭源公式复刻  
> 依赖：[`2026-09-28-industry-taxonomy-design.md`](./2026-09-28-industry-taxonomy-design.md)（宇宙、L1/L2 成员闭包、tradable 集合）  
> 数据字段源与 `float_mv` / `ts_code`：[`2026-10-01-market-data-contract-design.md`](./2026-10-01-market-data-contract-design.md)

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
| C2 | 进右侧只由 \(T\) 驱动；RS 永不单独触发；温且未进右侧不得开仓 | `test_C2_high_RS_cool_no_entry`, `test_C2_high_RS_warm_no_entry` |
| C3 | 节气不得作为强制开仓门控 | `test_C3_reject_solar_entry_gate` |
| C4 | 状态切换用交易日收盘 \(T\)；`right_side_days_natural` 仅自然日累加；字段分离 | `test_C4_calendar_split` |
| C5 | 个股/L2/L1 共用同一纯函数；合成口径见 §10；RS peer 见 §9.2 | `test_C5_same_engine_on_synthetic` |
| C6 | 统计**滞回后** \(T\) 的年化切换次数；超阈则 CI 失败（MVP 不自动改参） | `test_C6_transition_rate_cap` |

## 3. 数据输入

字段来源、涨跌停缺失、`float_mv` 落库、日历与 `ts_code` 规范见  
[`2026-10-01-market-data-contract-design.md`](./2026-10-01-market-data-contract-design.md)。

### 3.1 标的日线（必需）

- `ts_code`（Tushare 式 `XXXXXX.SH|SZ`）, `trade_date`  
- 信号用前复权 OHLC；账本成交另需 raw（由 data-contract / bars 提供）  
- `amount`；停牌标记、ST 标记  
- **`float_mv`（流通市值，元）落库，可空**；合成缺省权重见 data-contract §6.3（`null→1.0` 再归一，**不是**整篮改等权）  
- 价格口径（指标路径）：`price_adjust=qfq`（前复权），全市场统一  

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

\(P_t\)：前复权收盘价（bars/`daily_stock` 的 `close_qfq`）。

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

状态：`T_prev`（上一**交易日**输出的滞回后档；见冷启动）、`pending_target`、`pending_count`。

#### 5.3.1 冷启动 / 断档后首日（bootstrap）

当本交易日首次算出非 null 的 `T_raw`，且不存在可用的 `T_prev`（进程首日、或上一可算日之前为持续 null 且当时 `R=false`）：

1. 合成 `T_prev := 平`（仅作滞回锚点，**不**写入昨日输出）。  
2. `pending_target/count` 清空。  
3. 当日走正常 §5.3.2（从「平」向 `T_raw` 爬升/下降）。  

因此：**不会**在「无锚点的第一天」因直接 snap 到热/沸而跳过 `hysteresis_up` 进入右侧；从冷启动到热至少要跨过 max_step + 升温滞回。

#### 5.3.2 日报价步骤

每个**交易日收盘**，在算完 `T_raw` 后（`T_raw=null` 时本小节，见 §5.5）：

```text
desired = T_raw
delta = rank(desired) - rank(T_prev)

# A. 极端档邻接豁免：热→沸、寒→冻 允许一步到位
if desired in {沸,冻} and T_prev in {热,寒} and same_side(desired, T_prev):
    stepped = desired
# B. 右侧内退出快路径：raw 已 ≤平 时，禁止在降温途中停在温/热
elif R == true and rank(desired) <= 0:
    stepped_rank = rank(T_prev) + clip(delta, -max_step, +max_step)
    if stepped_rank > 0:
        stepped_rank = 0          # 至少落到「平」，避免暴跌假温拖退出
    stepped = inv_rank(stepped_rank)
# C. 常规 max_step
else:
    stepped = inv_rank(rank(T_prev) + clip(delta, -max_step, +max_step))

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

退出快路径下的最坏滞后（`hysteresis_down=1`, `max_step=2`）：若持续 `T_raw≤平`，从 **沸** 至多 **1 个交易日**确认到 \(T=平\) 并可结束右侧（当日 pending 满足即退出）。夹具 `fsm_crash_boil_to_freeze` 必覆盖。

- 计数只在**交易日**递增。  
- 「首次达热」= 滞回后 \(T\) 首次进入 `{热,沸}`（含冷启动爬升后的首次）。  
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

### 5.5 未知态与 null 分流

| 情形 | `T` / 滞回 | FSM |
|------|------------|-----|
| 历史不足，不可算 | 输出 `T=null`；滞回**不**推进 | 不得新开 `R` |
| `R=false` 且当日 `T_raw=null` | 输出 null；滞回不推进；**不**用旧热填充 | **禁止**进入右侧 |
| `R=true` 且当日 `T_raw=null`（短停牌等）且 **非** `hard_frozen` | FSM 用 `T_fill = T_last_valid`；可标 `T_filled=true` | 用 `T_fill` 做存续/退出；**不**因短 null 清 `R`；节气按 §8.2 可算才推进 |
| `hard_frozen=true` 且 `R=true` | 见下；停止推进滞回/天数/节气 peak | **结束右侧**（与温度退出同形）：`R=false`，立秋，emit `EXIT_RIGHT`（`detail.exit_kind=forced_exit_untradable`） |

**`hard_frozen`（导出布尔，MVP 钉死）**

```text
hard_frozen := is_st
            OR (explicit_hard_freeze_flag from data layer)  # 如长期停牌由行情契约置位
```

- **不含**普通 1～数日 `is_suspended` / 单日 `T_raw=null`（那些走上一行软填）。  
- MVP **不**另定「停牌连续 N 日」阈值；若以后要加，须进 data-contract + 新 `param_version`。  
- 一旦 `hard_frozen` 在 `R=true` 时成立：**结束本段右侧**（避免账本强平后 `R` 仍 true、无法再 `ENTER_RIGHT` 的死锁）。恢复可交易后须重新满足进入条件才会 `ENTER_RIGHT`。

夹具：`fsm_untradable_freeze` 改为「短不可算软冻不立秋」；新增 `fsm_st_ends_right`：`R` 中变 ST → 当日 `EXIT_RIGHT` + 立秋 + `R=false`。

## 6. 右侧状态机

### 6.0 事件枚举（与 ops `signal_event.event` 对齐）

| `event` | 何时写入（每标的×日至多一行该 event，除非注明） | `tag_*` | 账本 |
|---------|--------------------------------------------------|---------|------|
| `ENTER_RIGHT` | §6.2 进入右侧成功的收盘 | `tag_warm_to_hot=true` | **唯一**开仓信号 |
| `EXIT_RIGHT` | 温度退出（平及以下）**或** `hard_frozen` 结束右侧 | `tag_warm_to_flat=true` | **唯一**常规平仓信号；`detail.exit_kind`=`temperature`\|`forced_exit_untradable` |
| `WARM_TO_HOT` | **仅**存续期再确认：`R=true` 且 `T_prev_valid=温` 且 \(T_{fsm}\in\{热,沸\}\)`；**进入日不写此 event**（进入日只有 `ENTER_RIGHT`） | `tag_warm_to_hot=true` | **不**开仓 |

禁止：仅凭 `tag_warm_to_hot` / 仅凭 `WARM_TO_HOT` 开仓。

### 6.1 评价时点

- **状态转移**（进入/结束、温转热/温转平）：仅在**交易日收盘**，使用当日 FSM 输入温度 \(T_{fsm}\)（见下）。  
- **自然日累加**：每个自然日日终，若 `R=true` 且当日未触发结束，则 `right_side_days_natural += 1`。  
- 非交易日**不**新开右侧。  
- 每日先判 `hard_frozen`（§5.5）；若因此结束右侧，**不再**用温度做同日进入。

定义：

- \(T\)：§5.3 滞回后输出（可 null）。  
- \(T_{fsm}\)：若 `R=true` 且 \(T\) 为 null 且非 hard 结束 → `T_last_valid`；若 `R=false` 且 \(T\) 为 null → **跳过本日 FSM 转移**（保持 `R=false`）；否则 \(T_{fsm}=T\)。  
- `T_prev_valid`：**上一交易日**用于 FSM 的 \(T_{fsm}\)。用于温→热再确认（只产 `WARM_TO_HOT`）。

### 6.2 语义表

| 事件 | 条件 | 副作用 |
|------|------|--------|
| 进入右侧 | `R=false` 且 \(T_{fsm}\in\{\text{热},\text{沸}\}` 且非 `hard_frozen` | `R=true`；天数置 0；钉 `P0`/`atr_pct_entry`；**`signal_event=ENTER_RIGHT`**；`tag_warm_to_hot=true`；节气按 §8 |
| 存续 | `R=true` 且 \(T_{fsm}\in\{\text{温},\text{热},\text{沸}\}` 且非 hard 结束 | `days_trading +=1`（进入日不加）；若再确认则 **`WARM_TO_HOT`** + tag |
| 结束右侧（温度） | `R=true` 且 \(T_{fsm}\in\{\text{平},\text{凉},\text{寒},\text{冻}\}` | `R=false`；**`EXIT_RIGHT`**（`exit_kind=temperature`）；立秋；score=null |
| 结束右侧（不可交易） | `R=true` 且 `hard_frozen` | 同上，但 `exit_kind=forced_exit_untradable` |
| 未进入 | `R=false` 且 \(T_{fsm}=\text{温}\) | **永不**因温单独开仓 |

说明：

- **`tag_warm_to_flat` / 「温转平」= 右侧退出**（含硬冻结束），不要求前一日必须是「温」。  
- **`tag_warm_to_hot`**：进入日或再确认；再确认**不**重置天数、**不**产生 `ENTER_RIGHT`。  
- **危险信号（§11）永不改写 `R`/天数**。  
- **立秋**：仅结束当日；次日 `R=false` → `solar_term=null`；结束日 `stage_score`/`raw`=null。

### 6.3 伪代码

```text
# 交易日收盘（已完成 §5）：
tag_warm_to_hot = false
tag_warm_to_flat = false
just_exited_today = false
solar_term = null if not R else <§8 计算中的节气>

# 1) 硬冻优先：结束右侧（与温度退出同形，避免账本强平后 R sticky）
if R and hard_frozen:
  R = false
  tag_warm_to_flat = true
  solar_term = 立秋
  stage_score = null
  stage_score_raw = null
  stage_score_peak = 0
  right_side_days_natural = 0
  right_side_days_trading = 0
  just_exited_today = true
  emit EXIT_RIGHT (detail.exit_kind=forced_exit_untradable)
  # 本日不再温度进入 / 再确认
else:
  if T is null and not R:
    pass   # 跳过转移；不填充
  else:
    T_fsm = T_last_valid if (T is null and R) else T

    if not R:
      if T_fsm in {热, 沸} and not hard_frozen:
        R = true
        right_side_days_natural = 0
        right_side_days_trading = 0   # 进入收盘 = 0；之后每个存续交易日 +1
        P0 = P_t
        atr_pct_entry = ATR(atr_len)_t / P_t
        stage_score_peak = 0
        tag_warm_to_hot = true
        solar_term = 谷雨             # 进入日强制；见 §8.2
        stage_score = 0
        stage_score_raw = 0
        emit ENTER_RIGHT              # 唯一开仓；不另写 WARM_TO_HOT
    else:
      if T_fsm in {平, 凉, 寒, 冻}:
        R = false
        tag_warm_to_flat = true
        solar_term = 立秋              # 仅本日；强制，不跑 §8 切段
        stage_score = null            # 对外禁止发 0
        stage_score_raw = null
        stage_score_peak = 0          # 内部复位，供下次进入
        right_side_days_natural = 0
        right_side_days_trading = 0
        just_exited_today = true
        emit EXIT_RIGHT (detail.exit_kind=temperature)
      else:
        right_side_days_trading += 1
        if T_prev_valid == 温 and T_fsm in {热, 沸}:
          tag_warm_to_hot = true
          emit WARM_TO_HOT            # 再确认；不开仓
        solar_term = §8(peak)         # 谷雨…大暑；只前进；不可算则保留昨值

    T_prev_valid := T_fsm             # 供下一交易日
    if T is not null:
      T_last_valid := T

# 每个自然日日终（含非交易日）：
if R and not just_exited_today:
  right_side_days_natural += 1
```

`right_side_days_trading` = 进入之后、仍为 `R` 的**后续**交易日收盘次数；进入当日为 0（§8 进入日强制谷雨，属有意）。

### 6.4 FSM 夹具（命名，CI 必跑）

| ID | 场景 | 期望要点 |
|----|------|----------|
| `fsm_enter_hyst` | 从平爬升，热连续不足 `hysteresis_up` | 不进入；满滞回后进入 |
| `fsm_enter_boil` | 滞回后首次档为沸（未经展示「热」） | 进入；`tag_warm_to_hot` |
| `fsm_no_enter_warm` | 长期温且 `R=false` | 始终不进入 |
| `fsm_persist_warm` | 热→温 | 存续；`days_trading` 增加 |
| `fsm_exit_warm_to_flat` | 温→平 | 结束；天数 0；立秋仅当日 |
| `fsm_exit_hot_to_flat` | 热→平 | `tag_warm_to_flat` 真（非字面温→平） |
| `fsm_exit_boil_to_cool` | 沸→凉 | 同上 |
| `fsm_crash_boil_to_freeze` | 右侧内 `T_raw` 骤至冻 | 退出快路径：不经假温存续；≤1 日可到平并结束（默认参） |
| `fsm_reconfirm` | 右侧内温→热 | `tag_warm_to_hot`；**`WARM_TO_HOT` 事件**；无 `ENTER_RIGHT`；天数不重置 |
| `fsm_reentry` | 结束后再次热 | 重新进入；`ENTER_RIGHT`；天数从 0 |
| `fsm_null_in_R` | `R=true` 间隔短 null（非 hard） | 用 fill；不误结束；再确认夹具可接 |
| `fsm_null_not_R` | `R=false` 且 null，即使 `T_last` 曾为热 | **不**进入 |
| `fsm_fri_mon` | 周五确认进入 | 周末 `days_natural` +2；周一 `days_trading` 符合 §6.3 |
| `fsm_bootstrap` | 冷启动首日 `T_raw=热` | 当日不因 snap 进入；锚点为平再爬升 |
| `fsm_untradable_freeze` | `R=true` 短停牌/`T_raw=null`（非 ST） | 软冻：不立秋、不清 `R`；恢复后继续 |
| `fsm_st_ends_right` | `R=true` 当日变 ST（`hard_frozen`） | `EXIT_RIGHT`（`forced_exit_untradable`）+ 立秋 + `R=false` |

另：`test_C2_high_RS_warm_no_entry` — RS=99 且 \(T=温\)、`R=false` → 不进入。  

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
| 谷雨 | 蛰伏起点；**进入日强制**为此档（不论当日波动） |
| 立夏 | 萌芽 |
| 夏至 | 发展 |
| 小暑 | 破圈加速 |
| 大暑 | 后段拥挤 |
| 立秋 | **仅右侧结束当日**（`R=false` 的一日例外）；次日若 `R=false` 则为 null |

### 8.2 因果进度（无前视）

入口冻结：`P0`、`atr_pct_entry = ATR(atr_len)/P`（进入日）。

**进入日（`days_trading=0`）**：强制 `solar_term=谷雨`，`stage_score=stage_score_raw=0`，`stage_score_peak=0`。**不**把当日 `v`（或完整 Scorer）写入 peak——避免热/沸高 `σ%ile` 在 g=d=0 时顶穿谷雨切点。

**结束日（`R` 当日由 true→false）**：强制 `solar_term=立秋`；**不**跑切段；对外 `stage_score`/`stage_score_raw`=**null**（内部可清 `peak` 供下次进入，但**禁止**把清零后的 0 当作结束日对外分数）。次日若 `R=false`，`solar_term=null`。

**节气可算才推进**（与 §5.5 对齐，MVP 一句规则）：存续日须 `R=true` 且当日 `P_t` 与 `σ%ile` 均可算，才更新 `stage_score_*` / 谷雨…大暑。若仅 `T_raw=null` 走 `T_fill`、但价或波动不可算（短停牌等）：**保留昨日** `solar_term` 与 `stage_score_peak`，不抬 peak；FSM 仍可用 `T_fill` 判存续/退出。`hard_frozen`（ST / 显式硬冻旗）走 §5.5：**结束右侧**（立秋 + `EXIT_RIGHT`），不是「冻住不立秋」。

进行中（`R=true`、非进入日、非结束日、且节气可算）：

```text
g_raw     = ln(P_t / P0) / max(atr_pct_entry, atr_floor)
g_raw_eff = max(g_raw, 0)              # 相对入口回撤不产生负进度；不得外推到 knots 负域
d_raw     = right_side_days_trading / stage_D0
v_raw     = σ%ile                      # 当日，允许波动推高阶段

g = piecewise_linear_clamp(g_raw_eff, knots_g)  # → [0,1]
d = piecewise_linear_clamp(d_raw, knots_d)
v = piecewise_linear_clamp(v_raw, knots_v)

stage_score_raw  = w_g*g + w_d*d + w_v*v
stage_score_peak = max(stage_score_peak_prev, stage_score_raw)
stage_score      = stage_score_peak    # MVP：只前进；切段只读 peak
solar_term       = cut(stage_score)    # 谷雨…大暑
```

**`piecewise_linear_clamp`（写死）**

- 结点按 x **严格升序**；相邻结点之间线性插值。  
- `x ≤ x_min` → 取左端点 y；`x ≥ x_max` → 取右端点 y。  
- **禁止**端点外外推；**禁止**对负 `g_raw` 直接查表（须先经 `g_raw_eff`）。

**只前进（MVP）**

- 对外暴露的 `stage_score` / `solar_term`（谷雨…大暑）取进入本段右侧以来 `stage_score_raw` 的**运行最大值**再切段（进入日除外：固定 0 / 谷雨）。  
- 回撤日可令 `stage_score_raw` 下降，但 **不得**把已公布节气退回更早档（无「小暑→夏至」）。  
- 立秋仅由右侧结束触发，不是 score 回落。  
- 若未来要「可回退」，须新 `param_version` + 滞回带宽，**不**在本 MVP 混用。

**初值 knots（写入参数表）**

| 输入 | 结点 (x → y) |
|------|----------------|
| `knots_g` | (0→0), (0.5→0.25), (1.5→0.55), (3.0→0.8), (5.0→1.0) |
| `knots_d` | (0→0), (0.25→0.3), (0.5→0.55), (1.0→0.85), (1.5→1.0) |
| `knots_v` | (0→0), (0.5→0.2), (0.75→0.5), (0.9→0.8), (1.0→1.0) |

切段（读 `stage_score` = peak；进入日跳过）：

| stage_score | 节气 |
|-------------|------|
| < 0.15 | 谷雨 |
| < 0.35 | 立夏 |
| < 0.55 | 夏至 |
| < 0.75 | 小暑 |
| ≥ 0.75 | 大暑 |

校准：只允许 walk-forward / 留出年改 knots、切点或权重；全样本拟合禁止。变更 → 新 `param_version`。标定 KPI 见 §8.8。

**权重说明**：`w_g,w_d,w_v = 0.55, 0.25, 0.20` 为 **MVP 先验初值**（偏涨幅、时间与波动为辅），**非**数据训练得出；上线后按 §8.8 迭代。`v` 从**进入后的第一个可算存续日**起才进入加权。

**已知张力（文档承认）**：`w_d=0.25` 会把「拖久但没涨」推高档位，与「大暑=爆发拥挤」叙事冲突。标定须盯 §8.8 K5；必要时降 `w_d` 或加「进小暑/大暑须 `g_raw_eff` 地板」补丁（新版本），**不得**用主策略 PnL 调权。

### 8.3 MVP 不做

独立「下行节气」树；时长分布时间桶；节气预测；按 score 回退档位（见 §8.2 只前进）；`require_solar_term_for_entry` 类配置（实现层应拒绝）。

### 8.4 稳定契约（换打分器也必须遵守）

节气对系统其余部分只暴露下列契约；**线性公式与未来神经网络均为契约内部的一种实现**：

| 项 | 约定 |
|----|------|
| 启用 / 输出时机 | **存续** `R=true` → `{谷雨…大暑}`；**结束当日** `R=false` 且 `solar_term=立秋`（一日例外）；**其它** `R=false` → `solar_term=null` |
| 进入日 | 强制谷雨；`stage_score=0`；Scorer/`v` 不写入 peak |
| 因果 | 特征与分数只用 ≤ 当日收盘可得信息；入口锚点 \(P_0\)、`atr_pct_entry` 在进入日冻结 |
| 可算 | 价或 `σ%ile` 不可算则不推进 peak/标签（§8.2）；`hard_frozen` 结束右侧见 §5.5 |
| 输入（公开） | 至少包含可复现的 \(g\_raw,d\_raw,v\_raw\)（或同语义特征）；新增特征须进 allowlist 与 `param_version` |
| 分数输出 | 存续日 `stage_score ∈ [0,1]`（MVP=peak）；**结束日与非右侧日 `stage_score`/`stage_score_raw`=null**（禁止发 0 冒充） |
| 单调（MVP） | 同一次右侧内，谷雨…大暑只前进不回退；立秋除外 |
| 禁门控 | 实现与配置层拒绝「必须某节气才允许开仓/进右侧」 |
| 版本 | 任何打分器或切段变更 → 新 `param_version`；历史截面按当时版本解释 |
| 验收 | 用 §8.8 标定 KPI + §8.9 夹具，**不用**主策略盈亏作唯一 loss（§8.7） |

换模型时：**接口与禁令不变**，只替换 `stage_score_raw = Scorer(features)` 的内部实现；进入日强制谷雨、peak、立秋与 null 分数规则仍由契约层执行。

### 8.5 为何 MVP 选线性 `0.55g+0.25d+0.20v`，而非神经网络

1. **角色匹配**：节气是右侧进度**标签**，不是买卖信号；线性加权足够表达「涨幅为主、时间/波动为辅」，无需高容量拟合。  
2. **可解释**：Issue / 人工抽查可直接读「因涨幅到了小暑」；NN 黑盒不利于纪律叙事与排错。  
3. **样本与运维**：上线初期完整右侧路径少、分布漂移大；NN 易过拟合噪声跳档，且要模型文件、训练流水线、特征泄漏审查——超出 Actions+SQLite MVP。  
4. **版本可比**：三个权重 + knots 变更可 diff；网络权重难以做「两次日报节气为何不同」的审计。  
5. **与主规则解耦**：主回测 `mvp_right_side_v1` 不读节气；先把线性标签跑稳，再谈复杂打分器，避免同时调试两套系统。

因此 MVP **默认且唯一实现**为 §8.2 线性式；NN 不在 P0/P1 范围。

### 8.6 何时可以考虑神经网络（或其它非线性打分器）

须**同时**满足，才允许立项替换 `Scorer`（仍守 §8.4）：

1. 线性方案已上线，且层 A（工程因果）长期稳定；  
2. **主门槛**：≥ **200** 段**完整开平路径** **且** 上线影子日历 ≥ **12** 个月可算样本。「完整开平」= 曾进入右侧且之后出现过一次立秋（**含早夭**，不要求途经大暑）；「≥2 个风格年」仅作参考，不得单独替代主门槛；并有 walk-forward 协议。可选另报「曾达小暑/大暑」覆盖率，**不**作 NN 门闩；  
3. 线性标定触顶：在留出集上反复调 cuts/权重后，§8.8 中带「触顶判定」的 KPI 仍连续两个季度未达标；  
4. 新 Scorer 在留出集上 §8.8 KPI 优于线性，且邻域/时间切片不崩；  
5. 主策略影子账本**不要求**因换节气打分器而变好（允许几乎不变）；若显著变差须能归因于标签误用而非隐瞒用盈亏训练；  
6. 交付物含：特征 allowlist、训练截止日、模型哈希进 `param_version` 元数据、可关闭回退到线性的开关。

未满足前，只允许调线性权重 / knots / `stage_cuts`。

### 8.7 为什么要防止用盈亏训练节气

1. **目标错位**：盈亏由「热进 / 平出 + 执行」主导；节气不在主规则路径上。用盈亏训节气 = 逼标签去解释噪声交易结果，学到的不是「右侧走到哪」。  
2. **泄漏与双重使用**：若用同一段收益既评主策略又当节气监督信号，会把执行、涨跌停、仓位拒单等微观结构写进进度条，样本外易失效。  
3. **激励坏纪律**：模型可能把「随后大涨」标成更早节气或反之，诱导人把节气重新当成开仓滤镜，违反 §8.3 / §8.4 禁门控。  
4. **不可审计**：盈亏最优的黑盒切档无法向 Issue 读者解释「为何今天是大暑」。  

允许的监督/标定信号：§8.8 KPI、进入后分段实现波动、拥挤代理、人工「早/中/后期」抽查——**显式与主策略 PnL 分离**。

### 8.8 标定 KPI（初值，可宽后收）

统计宇宙：评估窗内实体×交易日。  
- **占用类（K2/K3）**：`solar_term ∈ {谷雨…大暑}` 的日（**不含**立秋行；立秋行单独计数）。  
- **大暑子集**：同上且 `solar_term=大暑`。  
变更权重/knots/cuts 时用**同一留出协议**对比；**禁止**用层 C/L 的策略净收益作唯一调参目标。

| ID | 指标 | MVP 初阈 | 触顶判定（线性仍可立项 NN 前须碰壁） |
|----|------|----------|--------------------------------------|
| K1 | 单日节气跳 ≥2 档（谷雨…大暑序）占比 | < 3%（分母=相邻两日均有谷雨…大暑标签的转移日） | 调参后仍 ≥ 3% |
| K2 | 谷雨日占比 | ∈ [15%, 45%]（分母=占用类日） | 调参后仍持续越界 |
| K3 | 大暑日占比 | ∈ [5%, 25%]（分母=占用类日） | 同上 |
| K4 | 后期更抖 | 小暑∪大暑日的 **当日 `σ_n`（与温度特征同一因果定义）** 的中位数 / 立夏日同指标中位数 ≥ 1.2；同宇宙、仅用 ≤ 当日信息；任一侧样本日 < 30 则该窗 K4 标 `insufficient` 不判触顶 | 调参后仍 < 1.2（样本充足时） |
| K5 | 「高 d 低 g 却大暑」纯度 | `count(d_raw≥1.0 ∧ g_raw_eff<0.5 ∧ term=大暑) / count(term=大暑)` < 8%；大暑日数 < 20 则 `insufficient` | 调参后仍 ≥ 8% |
| K6 | 同一次右侧内出现节气回退（非立秋） | = 0（只前进契约） | 实现 bug，非调参 |

阈值可随 `param_version` 收紧；放宽须记修订理由。Issue/周报建议展示 `stage_score` 与 g/d/v 分解及 K5 监控。

### 8.9 节气夹具（命名，CI 必跑）

| 夹具 ID | 断言要点 |
|---------|----------|
| `solar_entry_grain_rain` | 进入日即使 `σ%ile≥0.9`（高波动）→ **仍谷雨**；`stage_score=0` |
| `solar_jump_on_spike` | 进入**后**短窗暴涨使 `g_raw_eff` 跨多结 → 允许单日跳档，但记录供 K1 |
| `solar_drawdown_no_retreat` | 已达小暑后深回撤（`g_raw<0`）→ 仍小暑（或峰值档），**不**退夏至；`g_raw_eff=0` |
| `solar_early_exit_liqiu` | 右侧仅数日即温转平 → 结束日立秋；不要求途经大暑 |
| `solar_exit_day_liqiu` | 结束日：`right_side=false`，`solar_term=立秋`，`stage_score`/`stage_score_raw` **is null**（不是 0），不输出大暑等 |
| `solar_clamp_high` | `g_raw_eff>5`（或超右端）→ g 分量 = 1.0，无 NaN/外推 |
| `solar_halt_no_advance` | `R=true` 且价/`σ%ile` 不可算（短间隙，非 `hard_frozen`）→ peak/节气标签不前进、不立秋；恢复可算后继续 |

实现：`fixtures/solar_*.json`（或与 FSM 同目录命名约定）；`test_solar_suite` 全绿。

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
2. 合成：成分日收益按 **流通市值 `float_mv`** 加权。缺市值公式（钉死）：`w_raw = float_mv if 有值且>0 else 1.0`，再对成员集归一（market-data-contract §6.3）；**禁止**用今日 spot 回刷历史日市值。  
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

**规范：危险信号 / 开香槟 / 波动率放大 均不修改 `R`、天数或节气。** 策略层可据此减仓，而指标层右侧状态仍只由 \(T_{fsm}\) 驱动。

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
stage_score                 # [0,1] peak；进入日=0；结束日与非右侧=null（禁止用 0 表示立秋行）
stage_score_raw             # 可选；结束日/非右侧=null
g_comp, d_comp, v_comp      # 可选；归一化后分量，便于标定；结束日 null
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
| `solar_advance_only` | true | MVP 只前进；false 须新版本+滞回 |
| `solar_g_floor` | 0 | `g_raw_eff=max(g_raw, floor)` |
| `solar_kpi_*` | 见 §8.8 | K1–K5 初阈 |
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
| `test_C2_high_RS_warm_no_entry` | 强制 RS=99 且 \(T=温\)、`R=false` → 不进入 |
| `test_C3_reject_solar_entry_gate` | 策略配置若要求节气才开仓 → 校验器拒绝 |
| `test_C4_calendar_split` | `fsm_fri_mon`：`days_trading` / `days_natural` |
| `test_C5_same_engine_on_synthetic` | 人造价序列个股函数 vs 标为 l2 调用结果一致；peer 为 `local_l2` |
| `test_C6_transition_rate_cap` | 夹具序列年化 `temp_transitions` ≥80 → 失败（或标参不合格） |
| `test_temp_raw_gold` | ≥20 向量决策树命中 |
| `test_hysteresis_max_step` | 含退出快路径与冷启动锚点=平 |
| `test_fsm_suite` | §6.4 全部命名夹具 |
| `test_solar_suite` | §8.9 全部命名夹具 |
| `test_solar_kpi_report` | 评估窗可产出 K1–K6；K6 硬失败，其余告警 |
| `test_danger_no_mutate_R` | 危险信号触发后 `R`/天数不变 |
| `test_RS_peer_universes` | 三类 `universe_id` 隔离 |
| `test_RS_eligibility_tradable` | ST/停牌不进 `local_stock` peer |
| `test_colinearity_story` | 凉/寒 + RS≥80 存在 |
| `test_T_S_spearman` | ≥ `spearman_min` |

### 14.2 FSM / 其它

- 以 §6.4 夹具为准，不以本段散文替代。  
- 历史不足 → null；主策略回测不得依赖节气门控。  
- 立秋仅退出日（`R=false` 一日例外）；结束日 `stage_score` 为 null；危险标签不改 `R`。  
- 节气以 §8.9 夹具 + §8.8 KPI 为准；进入日强制谷雨；回撤不退档；不可算不推进标签。

### 14.3 可选外校准

外部 API 档位一致率：监控仪表，默认不设硬阈。

## 15. 已知漏洞与 backlog

| ID | 问题 | 方向 |
|----|------|------|
| V1 | 阈值非官方真值 | 外校准 + 域搜索 |
| V2 | \(S\) 粗糙 | 学权重或 MVP 隐藏 |
| V3 | 节气事后标签 / 高 d 低 g 伪大暑 | 保持 C3；盯 K5；必要时降 w_d 或 g 地板 |
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
| 2026-09-30 | FSM review 修订：冷启动锚点=平；`T_prev_valid`；null 分流；退出快路径（禁假温拖出）；温转平=退出事件；立秋仅当日；危险不改 R；不可算冻结；§6.4 命名夹具扩表 |
| 2026-09-30 | §8 增补：稳定契约；MVP 线性权重理由；NN 启用时机；禁止用盈亏训节气 |
| 2026-09-30 | 节气 review Must-fix：`g_raw_eff`；clamp；只前进 peak；结束日强制立秋；§8.8 KPI；§8.9 夹具；NN 主门槛 200 段且 12 月影子 |
| 2026-09-30 | 节气二次修补：进入日强制谷雨；立秋行 score=null；K4=`σ_n`、K5 分母=大暑日；可算才推进+`solar_halt_no_advance`；NN「完整开平」=enter→立秋 |
| 2026-10-01 | §3/`float_mv` 与 market-data-contract 对齐：落库、空则等权；ts_code Tushare 式 |
| 2026-10-01 | 合成权重公式对齐 data-contract §6.3（null→1.0 再归一） |
| 2026-10-01 | §3.1 去掉易误解的「等权」措辞，改指 §6.3 |
| 2026-10-01 | 跨 spec 对齐：§6.0 事件枚举；`hard_frozen`=ST/显式旗且结束右侧；软冻≠硬冻；伪代码 emit `ENTER`/`EXIT`/`WARM_TO_HOT` |
