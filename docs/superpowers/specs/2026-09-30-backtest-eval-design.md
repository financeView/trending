# 趋势信号回测与评估设计

> 状态：草案  
> 日期：2026-09-30  
> 依赖：  
> - [`2026-09-29-trend-metrics-engine-design.md`](./2026-09-29-trend-metrics-engine-design.md)（温度 / 右侧 FSM）  
> - [`2026-09-30-ops-action-and-eval-design.md`](./2026-09-30-ops-action-and-eval-design.md)（`signal_event`、db、流水线）  
> - [`2026-10-01-market-data-contract-design.md`](./2026-10-01-market-data-contract-design.md)（`limit_*` / raw·qfq / 日历）  
> 本文从运维 spec 拆出，专管「怎么评估信号好不好」。

## 0. 先澄清误解

**不是**「只统计上线后的实盘收益」。评估分三条轨，可并行：

| 轨 | 数据 | 何时 |
|----|------|------|
| **H 历史纸面** | 用历史 bars 因果重放信号 + 模拟成交 | MVP 起就可做 |
| **L 上线后影子账本** | 每日 Actions 已落库的真实信号，次日按规则记模拟盈亏 | 流水线上线后 |
| **M 真实资金（可选）** | 人工/券商成交 | 明确试点后才开；**不作**算法唯一裁判 |

上线后的 L 轨很重要（无前视、分布漂移可见），但不能替代 H：冷启动前几个月样本太少，判不了。

---

## 1. MVP 默认交易规则（`rule_id = mvp_right_side_v1`）

与指标引擎右侧语义对齐；**唯一主结论规则**，避免调参乐园。

### 1.1 买入

| 项 | 设定 |
|----|------|
| 信号 | 交易日 **D 收盘** 出现 **`signal_event.event = ENTER_RIGHT` 且仅此**。不是任意「温」，不是「仅温未进右侧」，**不是**单独的 `tag_warm_to_hot`（再确认也会打该 tag，不得开仓）。 |
| 下单 | **下一交易日**开盘价买入（记作 D+1；见 §4.0） |
| 涨跌停 | D+1 开盘不可买 → `unfilled_buy`，该信号作废（MVP 不排队） |
| 其它过滤 | 可算宇宙、非 ST；可选对照档 `RS≥70`（不进主结论） |

### 1.2 卖出（重要纠正）

| 项 | 设定 |
|----|------|
| 信号 | 交易日 **E 收盘** 出现 **`EXIT_RIGHT`（唯一卖出事件）**。`detail.exit_kind`：`temperature`（温度落到平及以下）或 `forced_exit_untradable`（`hard_frozen`，见 §4.1）。**禁止**另开「非事件强制出清」路径；**禁止**仅凭当日 \(T\) 过滤卖单（硬冻退出时 \(T\) 仍可能是温/热）。 |
| 下单 | **下一交易日**开盘价卖出（E+1） |
| 涨跌停 | E+1 开盘不可卖 → `unfilled_sell`；MVP：**下一交易日**开盘再试 |

**不是「回落至温的次日卖出」。**「温转平」是退出事件的产品名（含硬冻结束），不要求字面温→平。

依据现行 FSM：

- 已进右侧后 **\(T=\text{温}\)** = **存续**，不是结束。  
- 若「回落至温就卖」，会系统性砍掉产品定义里的右侧中段，和温度/节气设计打架，回测也无法检验「右侧状态机」本身。

若要做激进对照，另立 `rule_id = mvp_exit_on_warm_v0`（温即出），**仅作对照表，不进主结论**。

### 1.3 持有期示意

```text
… 平/凉 … → D收盘 ENTER_RIGHT → 下一交易日开买入
→ 持有（可经 温/热/沸，含回落到温）
→ E收盘 EXIT_RIGHT（temperature 或 forced_exit_untradable）→ 下一交易日开卖出
（周五确认 → 周一开；见夹具 fill_fri_enter_mon_buy）
```

### 1.4 组合与成本（主规则写死）

| 项 | MVP |
|----|-----|
| 宇宙 | §4.1：主结论 = `tradable` 个股；信号与成交同一宇宙 |
| 仓位 | 等权；单票目标权重 `1/N_cap`（`N_cap=20`）；**不做**日终再平衡 |
| 拒单 | 名额满 → `rejected_no_slot`；现金不够 1 手 → `rejected_no_cash`（均不排队） |
| 成本 | §4.3 `config/eval/costs.yaml` |
| 复权 / 成交价 | §4.2 |

细则一律以 **§4** 为准。

### 1.5 成交语义总表

| 事件 | 确认 | 意图成交 | 不可成交 |
|------|------|----------|----------|
| 买 | D 收盘 `ENTER_RIGHT` | 下一交易日开 | 涨停/停牌等 → 跳过（§4.4） |
| 卖 | E 收盘 `EXIT_RIGHT`（含两种 `exit_kind`） | 下一交易日开 | 跌停/停牌 → 延期（§4.4） |

---

## 2. 评估分层（仍适用）

### 2.1 层 A — 工程因果（门禁）

幂等、≤D 数据重算一致、版本钉死、金标/FSM 单测。未过不准谈收益。

### 2.2 层 B — 信号前瞻（无仓位）

对 `ENTER_RIGHT`：+5/+10/+20 日收益与相对 L2/宇宙超额；进入→退出持有期分布；分 L1 切片。  
**节气切片**不要用进入日标签（进入日固定谷雨，几乎退化）：按**持有期交易日**的当日节气，或按该段**曾达最高节气 / 退出队列**分桶。  
节气切片的**标签质量**以 metrics spec §8.8（K1–K6）为准，不把层 B/C 收益当节气调参目标。  
回答「信号后价格如何」，不是「策略期望」。

### 2.3 层 C — 纸面账本（本 spec 核心）

严格执行 §1 + §4，输出 §4.7 / §4.11。主指标：

- 净收益、最大回撤、胜率、盈亏比、平均持有交易日、年化换手  
- `unfilled_*` / `rejected_*` 比率  
- 相对沪深300、相对「随机同日开仓」基准（§4.9）  

**全样本一条曲线好看不作数**；须满足 §4.8 walk-forward + 邻域不翻转。

### 2.4 层 L — 上线后影子（实盘日历，非真实资金）

每日流水线已落库的 `signal_event` → 同一执行引擎（§4.6）按 §1 记影子成交到 `paper_fill`（§4.7）。  
与 H 的差别见 §4.10：信号来自**当时上线的 `param_version`**，反映真实漂移。

**真实资金 M**：另表；不与 H/L 混算；不作唯一裁判。

---

## 3. 决策矩阵（何时算「可用」）

| 状态 | A | B | C（历史） | L（影子，≥N 笔） | 动作 |
|------|---|---|-----------|------------------|------|
| 不可用 | 红 | — | — | — | 修引擎 |
| 观察 | 绿 | 弱/乱 | — | — | 只跑 Issue |
| 可小仓试点 | 绿 | 进入后超额尚可 | 相对基准不崩（软） | 方向不打架 | 人工按 Issue |
| 可谈加仓/页面 | 绿 | 绿 | **§4.8 通过** | 影子与历史同向 | 开 UX |

`N` 初议：影子成交≥30 笔完整开平再看 L 列。C 列「绿」以 §4.8 为准，不以全样本曲线为准。

---

## 4. 执行与账本契约（H / L 共用）

H（历史纸面）与 L（影子）**必须共用同一执行纯函数**；只换信号源与输出落点。

### 4.0 交易日历（写死）

文中 **D+1 / E+1 / T-1** 一律指 **交易日** 滞后，不是自然日：

- `next_trade_date(D)`：D 之后第一个交易日（周五 → 下周一；节前 → 节后首日）。  
- `prev_trade_date(T)`：T 之前最后一个交易日。  
- 意图成交日 = `next_trade_date(确认日)`。  

夹具（CI）：`fill_fri_enter_mon_buy` — 周五 `ENTER_RIGHT` → 周一开盘买（非周六/日历 +1）。

### 4.1 宇宙与不可交易退出（`hard_frozen`）

| 项 | MVP |
|----|-----|
| 标的 | A 股个股；`member_set=tradable` |
| 新开仓资格 | 非 ST、非停牌、温度可算；否则不得买 |
| 信号范围 | 主结论只评估个股 **`ENTER_RIGHT` / `EXIT_RIGHT` 事件**；L1/L2 不做账本 |
| 对照 | 可选 `RS≥70` 子集另跑，不进主结论 |

**持仓遇不可交易（与 metrics `hard_frozen` 对齐）**

metrics：`hard_frozen`（MVP=`is_st` 或 data-layer 显式硬冻旗）且 `R=true` 时 **结束右侧**：emit `EXIT_RIGHT`（`detail.exit_kind=forced_exit_untradable`）、立秋、`R=false`。普通短停牌 / `T_raw=null` 走软填，**不**发该退出。

账本：消费同一 `EXIT_RIGHT` 做次日开卖（与温度退出同路径）；`paper_fill.exit_kind` 抄自 `detail.exit_kind`。

MVP 触发与延期：

- **触发**：确认日 `U` 收盘出现上述 `EXIT_RIGHT` 且 `exit_kind=forced_exit_untradable`（通常因 `is_st` / 显式硬冻旗）。  
- **不触发**：普通 1～数日停牌、`T_raw=null` 软填 → **不**合成强制卖；若已在卖出队列则按 §4.4 延期。  
- 动作：确认日=`U`，意图成交日=`next_trade_date(U)`。  
- 不可卖则进延期卖队列。  
- **禁止**在指标仍 `R=true` 时单独强平（否则 sticky-R，无法再 `ENTER_RIGHT`）。

### 4.2 价格与复权

| 用途 | 口径 |
|------|------|
| 指标 / FSM / 信号 | **前复权**收盘 |
| 意图成交价 | **`open_raw`**（未复权开盘）；库若无 raw，须全样本统一 `fill_price=adj_open` 并写入 summary |
| 涨跌停 | 仅 vendor / 当日东财写入的 `limit_up`/`limit_down`；**禁止**对 300/688 静默套用主板 10% |
| 净值盯市 | `close_raw` |

缺 `limit_*` → **`data_gap`**（MVP）。加厚历史样本时的可选推算见 market-data-contract **§5.2 `board_calc_v1`**（须显式改 `limit_rule`，本 MVP 默认不启用）。  
字段与源：[`2026-10-01-market-data-contract-design.md`](./2026-10-01-market-data-contract-design.md)。

MVP：**推荐** bars 含前复权 OHLC + `open_raw/close_raw` + `limit_up/limit_down` + `is_suspended` + `is_st` + 可空 `float_mv`。

### 4.3 `costs.yaml` 初值

**路径钉死**：`config/eval/costs.yaml`（代码只读此路径）。

```yaml
cost_version: v1
commission_rate: 0.0003
min_commission: 0
stamp_tax_sell: 0.0005
impact_bp_buy: 5
impact_bp_sell: 5
lot_size: 100
N_cap: 20
initial_cash: 1000000
limit_rule: vendor_fields      # MVP：缺字段 → data_gap；将来可选 board_calc_v1 见 market-data-contract §5.2
fill_price: open_raw
hs300_series: 000300.SH        # Tushare 式；summary 原样抄写
```

费用从现金扣；冲击改成交价。变更 → 新 `cost_version`。

### 4.4 涨跌停 / 停牌

**价格空间**：`limit_up`/`limit_down` 与比较用的开盘价均为 **raw**（`open_raw`）；禁止用 qfq 价比涨跌停（见 market-data-contract §5.0）。

判定在**意图成交日**开盘：

| 条件 | 买 | 卖 |
|------|----|----|
| `is_suspended` | `unfilled_buy`，作废 | `unfilled_sell`，下一交易日再试 |
| `open_raw >= limit_up` | `unfilled_buy`，作废 | MVP：**仍尝试成交**；仅当 `limit_up_unfillable=true` 时延期 |
| `open_raw <= limit_down` | 可买 | `unfilled_sell`，延期 |
| 涨跌停字段缺失 | `data_gap`，不得用收盘价顶替开盘价 | 同左 |

### 4.5 组合日历状态机

日终：`cash`、`positions{ts_code → shares, entry_date, entry_px, signal_date, exit_kind?}`、`pending_sells[]`。

每个交易日 `T` 顺序（写死）：

1. **延期卖**（`pending_sells`）→ §4.4 开盘试卖  
2. **到期卖**：确认日 = `prev_trade_date(T)` 的 **`EXIT_RIGHT`**（`detail.exit_kind=temperature|forced_exit_untradable`）→ 开盘卖  
3. **买入**：确认日 = `prev_trade_date(T)` 的 **`ENTER_RIGHT` 事件**、且无持仓 → 开盘买  
4. 日终 `close_raw` 估值  

**无**单独「扫描强制出清」步：`hard_frozen` 已由 metrics 在确认日收盘写成 `EXIT_RIGHT`，次日由步骤 2 消费。禁止账本在 `R=true` 时另开强平队列。

同日排序：卖先于买；买按确认日 `RS` 降序，同分 `ts_code` 升序。  
已持仓新 `ENTER_RIGHT` → `ignored_already_held`；无仓 `EXIT_RIGHT` → `ignored_flat_exit`。  
**禁止**仅凭 `tag_warm_to_hot` 买入。

仓位：

- `equity_ex_open` = **昨日**日终权益（已知近似：不用今开重估后再 sizing）  
- 目标市值 = `equity_ex_open / N_cap`；卖出回笼现金可用于**当日**后续买单  
- 手数 = `floor(目标 / fill_px / lot) * lot`；`<1` 手 → `rejected_lot`  
- 持仓数 ≥ `N_cap` → `rejected_no_slot`  
- 名额有、现金不够该票 1 手 → `rejected_no_cash`；买循环中每笔成交后更新 cash，继续按 RS 序尝试下一票  
- **不做**再平衡  

### 4.6 执行引擎接口

```text
fill_day(T, signals_on_prev_trade_date(T), book_state, bars, costs)
  → fills[], rejects[], book_state', equity_point
```

| 轨 | 信号源 | 调用方 |
|----|--------|--------|
| H | MVP **默认**：钉死 `param_version` **因果重算**整段；重放库内事件仅用于与 L 对账审计 | `paper_book.py` |
| L | 落库时的 `signal_event` 行（带稳定 `id`）；见 §4.10 不可变 | `live_shadow_step.py` |

流水线（ops）：交易日 `T` 的 bars + 截面/事件落库成功、且 **`run_meta(T).status=ok`**（及意图用到的确认日若已跑过亦须曾 `ok`，见 market-data §7.2 影子句）后，再 `fill_day(T, …)`（用 `prev_trade_date(T)` 的信号买/卖今开）。缺今开 bars 或 `status≠ok` → **不跑 L**，记 warn。

### 4.7 `trades` / `paper_fill` schema

```text
paper_fill / trades row:
  fill_id
  track              # H | L
  rule_id, cost_version, param_version, map_version
  signal_event_id    # L 必填；H 重算可为 null
  signal_date        # 确认日
  intent_date        # next_trade_date(signal_date)
  fill_date
  ts_code
  side               # buy | sell
  exit_kind          # temperature | forced_exit_untradable | null(buy)；与 signal_event.detail 对齐
  qty, px, costs
  status             # filled | unfilled_buy | unfilled_sell
                     # | rejected_no_slot | rejected_no_cash | rejected_lot
                     # | ignored_already_held | ignored_flat_exit | data_gap
  reject_reason
  run_id
```

权益：`date, equity, cash, n_pos, gross_exposure`。

**窗口末未平仓（KPI 写死）**

- 权益 / 最大回撤：用到 `to` 的 **MTM**（未平仓按 `to` 日 `close_raw`）。  
- `win_rate` / `profit_factor` / `avg_hold_days` / 随机配对：只用 **已平仓** 回合。  
- summary 必须含 `n_open_end`（`to` 日仍持仓数）。  
- 不得把未平仓假造成已平仓计入胜率。

**`vs_hs300`（一行算法）**

- 策略日收益 \(r_t = equity_t/equity_{t-1}-1\)（含现金）。  
- 沪深300用 `costs.yaml` 的 `hs300_series` 同日历日收益 \(b_t\)（优先全收益，否则价格指数，summary 注明 `hs300_kind`）。  
- `vs_hs300` = 窗口内 \(\prod(1+r)-\prod(1+b)\)（累计超额）；另可选报年化，非正式门禁。

### 4.8 Walk-forward 协议（层 C 门禁）

| 项 | MVP |
|----|-----|
| 日历 | 训练年只许叙述；**禁止**改主规则阈值；测试年 `Y` 出主数字 |
| 最少 | ≥ **2** 个完整测试年 |
| 邻域 | 4 键 × {+20%, −20%} = **8** 次：`adx_hot`,`adx_warm`,`hysteresis_up`,`hysteresis_down` |
| 主门槛（测试年须同时） | (1) **`vs_random` ≥ 0**（定义严格同 §4.9，配对等权均值，不是另算「累计组合超额」）；(2) `max_dd_strategy ≤ 1.2 * max_dd_random`（§4.9 曲线） |
| 邻域通过 | 8 次中 ≥ **6** 次满足：该次 run 的 `vs_random` > −5pct（绝对） |
| 失败 | 仅全样本好看，或主门槛/邻域未过 → 矩阵 C 不绿 |

禁止在测试年搜温/热阈值（§5）。初值可后续收紧，放宽须修订记录。

### 4.9 「随机同日开仓」基准

`random_mode=paired_hold`：

1. 仅对主规则 **已平仓** 回合：记录 `buy_fill_date`、持有交易日数 `H`（卖出与买入 `fill_date` 之间的交易日个数）。  
2. **冲突**：该日主策略 `positions` 已持有的 `ts_code`，以及同日主策略买入的 `ts_code`。  
3. 同日 tradable∖冲突 中均匀随机 1 票；同成本/涨跌停；买失败最多重抽 3 次。  
4. `vs_random` = 各配对净收益（扣成本后）的**等权平均**（WF 主门槛 (1) 直接用此值）。  
5. `max_dd_random`：**按 `buy_fill_date` 升序，同分按 `ts_code` 升序**，将配对净收益依次累加得一条曲线，再算该曲线最大回撤（跌幅幅度）；summary 抄写 `random_dd_method=paired_cumsum_by_buy_date`。  
6. `seed` 默认 42，写入 summary。

### 4.10 H vs L（L 上线前必读）

| | H | L |
|--|---|---|
| 信号 | 钉版本因果重算 | 消费落库 `signal_event.id` |
| 资金 | `initial_cash` 自窗口起 | MVP 接续单例 `shadow_book` |
| 输出 | `output/eval/{run_id}/` | **`trend.db.paper_fill`（事实源）** + `live_shadow/` 摘要 |

**L 与 ops 重跑（不可变）**

- `paper_fill` 表 **MVP 必在 `data/trend.db`**，随库 commit；须带 `signal_event_id` + 落库时 `param_version`。  
- 对已产生 L 行的记录：**禁止**因重跑覆盖事件而改写/删除（与 ops §3.3 一致）。  
- ops 重跑日 D：旧 `signal_event` 保留 + `superseded_by`；影子仍锚定原 `id`。  
- **消费定义**：某 `signal_event_id`（+ `side`）只要已存在任意 **终态** `paper_fill` 行，即视为已消费——包括 `filled` / `unfilled_*` / `rejected_*` / `ignored_*` / `data_gap`。新影子日 **只**处理尚无终态行的事件 id。  
- 未实现本条之前，**不要**把 L 列当作决策矩阵依据。

对账：每季用钉死 param 做近 60 日 H，与 L 的 `signal_event_id` 集合比对齐率；不一致记漂移，不单边改历史 L。

### 4.11 输入 / 输出 / 命令 / 夹具

**夹具（eval CI）**

| ID | 断言 |
|----|------|
| `fill_fri_enter_mon_buy` | 周五 ENTER → 周一开买 |
| `fill_enter_right_only` | 仅有 `tag_warm_to_hot` 再确认、无 ENTER → 不买 |
| `fill_forced_exit_st` | 持仓变 ST → metrics 当日 `EXIT_RIGHT`（`forced_exit_untradable`）→ 下一交易日开卖 |
| `fill_open_end_kpi` | 窗口末未平仓不进入 win_rate；`n_open_end≥1` |

**输入**：`cache/bars.db`；`trend.db`（L）；`config/eval/costs.yaml`；版本钉。

**输出**：

```text
output/eval/
  {run_id}/                 # H
    summary.json
    trades.parquet
    equity_curve.csv
    slices_by_l1.csv
    rejects.parquet
  live_shadow/              # L
    {asof}/summary_snip.json
```

`summary.json` 含 `n_open_end, vs_hs300, hs300_kind, vs_random, random_mode, seed, wf_pass`。

```bash
python scripts/eval/paper_book.py \
  --rule mvp_right_side_v1 \
  --from 2024-01-01 --to 2025-12-31 \
  --param-version … --map-version … \
  --cost-version v1 --seed 42

python scripts/eval/live_shadow_step.py --asof today
```

---

## 5. 明确不做（本期）

- 用回测去搜索温/热阈值后宣称「验证通过」  
- 以「回落至温即卖」作主规则  
- 分钟级/盘中温度  
- 多空对冲、杠杆  
- 把真实盈亏当唯一 KPI  
- 日终再平衡、最低佣金、卖出最长延期后强制市价（后置）  
- 用 `tag_warm_to_hot` 当开仓条件  

---

## 6. 与你问题的对照

| 你的说法 | 本 spec |
|----------|---------|
| 统计上线后实盘收益？ | **部分对**：要做上线后**影子账本**；同时必须有**历史纸面**；真钱可选且不唯一 |
| 温转热次日开买入？ | **否（字面温转热不够）**：须 **`ENTER_RIGHT`**；存续期温→热再确认只打 tag，**不开仓** |
| 涨跌停开盘不操作？ | **买：对（跳过）**；**卖：跌停则延期再卖**，不是永久不操作 |
| 回落至温次日卖？ | **不对**；主规则是 **`EXIT_RIGHT` 次日开卖**（温度退出或 `hard_frozen`）；温是持有 |

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-09-30 | 自运维 spec 拆出；锁定 mvp_right_side_v1；纠正「温即卖」 |
| 2026-09-30 | 层 B 节气切片指向 metrics §8.8 KPI；禁用层 B/C 收益调节气 |
| 2026-09-30 | 层 B 节气改为持有期/最高档/退出队列分桶，不用 ENTER 日标签 |
| 2026-09-30 | §4 执行与账本契约：宇宙、复权/成交价、costs 初值、涨跌停、组合状态机、H/L 接口、paper_fill、WF、随机基准 |
| 2026-09-30 | review 修补：交易日滞后；ST 强制出清；ENTER_RIGHT only；未平仓 KPI；拒单分裂；vs_hs300；WF 主门槛；随机冲突；L 事件不可变；costs 路径钉死 |
| 2026-09-30 | 二次修补：强制出清仅 ST/硬冻结；WF 对齐 vs_random；max_dd_random 曲线钉死；L 终态即消费；paper_fill∈trend.db |
| 2026-10-01 | 交叉引用 market-data-contract：MVP data_gap；预留 board_calc_v1 |
| 2026-10-01 | §4.4 明确 limit 与 open_raw 同为 raw 空间 |
| 2026-10-01 | 跨 spec：强制出清改走 metrics `EXIT_RIGHT`+`hard_frozen`（结束 R）；卖单只认 EXIT 事件 |
| 2026-10-01 | 清歧义：§1 卖=唯一 `EXIT_RIGHT`；删 §4.5 独立强平步；L 须 `run_meta=ok` |
